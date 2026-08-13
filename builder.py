# -*- coding: utf-8 -*-
"""Nuitka 构建命令的构造与执行

- build_command(cfg): 根据配置字典生成 Nuitka 命令行参数列表
- run_build(cfg, log_queue, stop_event): 在线程中执行打包, 逐行输出日志
"""

import os
import re
import shlex
import subprocess
import sys
import threading

_VERSION_RE = re.compile(r"[vV]?\s*(\d+(?:\.\d+)*)")


def _sanitize_version(value):
    """清洗 Windows 版本号: 自动去掉 V/v 前缀, 只保留数字点分; 非法返回空串。"""
    value = (value or "").strip()
    if not value:
        return ""
    m = _VERSION_RE.match(value)
    return m.group(1) if m else ""


def _split_extra(text):
    """将附加参数文本拆分为参数列表(兼容 Windows 命令行)"""
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return text.split()


def build_command(cfg):
    """根据配置字典构造 Nuitka 命令行参数列表"""
    cmd = [sys.executable, "-m", "nuitka"]

    mode = cfg.get("mode", "onefile")
    if mode == "module":
        cmd.append("--module")
    else:
        cmd.append("--standalone")
        if mode == "onefile":
            cmd.append("--onefile")

    if cfg.get("output_dir"):
        cmd.append("--output-dir=%s" % cfg["output_dir"])
    if cfg.get("output_filename"):
        cmd.append("--output-filename=%s" % cfg["output_filename"])

    if cfg.get("console"):
        cmd.append("--enable-console")
    else:
        cmd.append("--windows-console-mode=disable")

    if cfg.get("icon"):
        cmd.append("--windows-icon-from-ico=%s" % cfg["icon"])

    for plugin in cfg.get("plugins") or []:
        cmd.append("--enable-plugin=%s" % plugin)

    lto = cfg.get("lto", "auto")
    if lto in ("yes", "no"):
        cmd.append("--lto=%s" % lto)

    try:
        jobs = int(cfg.get("jobs") or 0)
    except (TypeError, ValueError):
        jobs = 0
    if jobs > 1:
        cmd.append("--jobs=%d" % jobs)

    # 始终自动确认下载(含首次 MinGW64 编译器), 避免无控制台窗口时被询问而卡住
    cmd.append("--assume-yes-for-downloads")
    if cfg.get("remove_output"):
        cmd.append("--remove-output")

    for item in cfg.get("data_dirs") or []:
        cmd.append("--include-data-dir=%s" % item)
    for item in cfg.get("data_files") or []:
        cmd.append("--include-data-files=%s" % item)
    for name in cfg.get("include_packages") or []:
        cmd.append("--include-package=%s" % name)
    for name in cfg.get("include_modules") or []:
        cmd.append("--include-module=%s" % name)
    for name in cfg.get("exclude_modules") or []:
        cmd.append("--nofollow-import-to=%s" % name)

    meta = (
        ("company_name", "--company-name"),
        ("product_name", "--product-name"),
        ("file_version", "--file-version"),
        ("product_version", "--product-version"),
        ("file_description", "--file-description"),
        ("copyright", "--copyright"),
    )
    for key, flag in meta:
        val = (cfg.get(key) or "").strip()
        if key in ("file_version", "product_version") and val:
            val = _sanitize_version(val)  # 版本号必须为数字点分, 自动去掉 V 前缀
        if val:
            cmd.append("%s=%s" % (flag, val))

    cmd.extend(_split_extra(cfg.get("extra_args") or ""))

    script = (cfg.get("script") or "").strip()
    if script:
        cmd.append(script)
    return cmd


def run_build(log_queue, stop_event, cfg):
    """在线程中执行 Nuitka 打包, 日志逐行放入 log_queue

    参数顺序与 BuildWorker 约定一致: (log_queue, stop_event, cfg)
    log_queue 消息格式: ("cmd",命令行) / ("line", 文本) / ("error", 文本) / ("done", 退出码)
    """
    cmd = build_command(cfg)
    log_queue.put(("cmd", " ".join(cmd)))
    code = run_process(cmd, cwd=os.path.dirname(cfg.get("script") or "") or None,
                       log_queue=log_queue, stop_event=stop_event)
    log_queue.put(("done", code))


def run_process(cmd, cwd, log_queue, stop_event):
    """启动子进程, 逐行输出日志到 log_queue, 支持通过 stop_event 取消

    返回退出码: 0 成功, -1 启动失败, -2 用户取消
    """
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
            cwd=cwd or None,
        )
    except Exception as exc:
        log_queue.put(("error", "无法启动命令: %s" % exc))
        return -1

    def pump():
        try:
            for line in proc.stdout:
                log_queue.put(("line", line.rstrip("\n")))
        except Exception:
            pass

    threading.Thread(target=pump, daemon=True).start()

    while proc.poll() is None:
        if stop_event.wait(0.2):
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
            log_queue.put(("line", "[已取消]"))
            return -2
    return proc.returncode

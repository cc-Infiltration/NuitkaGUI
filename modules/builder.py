# -*- coding: utf-8 -*-
"""Nuitka 构建命令的构造与执行

- build_command(cfg): 根据配置字典生成 Nuitka 命令行参数列表
- run_build(cfg, log_queue, stop_event): 在线程中执行打包, 逐行输出日志
"""

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading

_VERSION_RE = re.compile(r"[vV]?\s*(\d+(?:\.\d+)*)")

# 可运行 `python -m nuitka` 的解释器路径(解析后缓存)
_PYTHON_EXE = None


def _is_onefile_temp(path):
    """Nuitka onefile 解包临时目录特征: 在系统临时目录下且路径含 onefile_"""
    if not path:
        return False
    p = os.path.normcase(os.path.abspath(path))
    if "onefile_" in p:
        return True
    tmp = os.path.normcase(tempfile.gettempdir())
    return p.startswith(tmp) and "nuitka" in p


def _probe_nuitka(python):
    """探测指定解释器是否安装了 Nuitka"""
    try:
        proc = subprocess.run(
            [python, "-c",
             "import importlib.metadata as m;print(m.version('nuitka'))"],
            capture_output=True, text=True, timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _python_candidates():
    """按优先级返回候选解释器路径(去重)"""
    cands = []
    exe = sys.executable
    if exe and os.path.isfile(exe) and not _is_onefile_temp(exe):
        cands.append(exe)
    for name in ("python", "python3", "py"):
        p = shutil.which(name)
        if p and p not in cands:
            cands.append(p)
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            base = os.path.join(local, "Programs", "Python")
            try:
                for d in sorted(os.listdir(base), reverse=True):
                    p = os.path.join(base, d, "python.exe")
                    if p not in cands and os.path.isfile(p):
                        cands.append(p)
            except OSError:
                pass
    return cands


def resolve_python():
    """返回可运行 `python -m nuitka` 的真实解释器路径, 找不到返回 None。

    源码运行: sys.executable 即真实解释器, 直接用。
    编译产物运行: sys.executable 指向 onefile 解包临时目录(已失效),
    回退搜索 PATH 与常见安装位置的 Python, 并探测其已安装 Nuitka。
    结果缓存, 避免每次打包都探测。
    """
    global _PYTHON_EXE
    if _PYTHON_EXE:
        return _PYTHON_EXE
    for cand in _python_candidates():
        if _probe_nuitka(cand):
            _PYTHON_EXE = cand
            return cand
    return None


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
    """根据配置字典构造 Nuitka 命令行参数列表; 找不到可用解释器时返回 []"""
    python = resolve_python()
    if not python:
        return []
    cmd = [python, "-m", "nuitka"]

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
        # 把图标文件一并打进产物, 供运行时加载任务栏图标
        # (onedir 放到 dist 目录, onefile 放到解包目录, 与 sys.executable 同目录)
        cmd.append("--include-data-files=%s=%s" % (cfg["icon"],
                                                   os.path.basename(cfg["icon"])))

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
        # 目标脚本同目录存在 styles/*.qss 时(工具自身布局), 一并打进产物,
        # 供运行时加载亮/暗主题样式(放到 dist 的 styles/ 子目录)。
        style_dir = os.path.join(os.path.dirname(os.path.abspath(script)), "styles")
        if os.path.isdir(style_dir) and any(
                f.lower().endswith(".qss") for f in os.listdir(style_dir)):
            cmd.append("--include-data-files=%s=styles/" %
                       os.path.join(style_dir, "*.qss"))
        cmd.append(script)
    return cmd


def run_build(log_queue, stop_event, cfg):
    """在线程中执行 Nuitka 打包, 日志逐行放入 log_queue

    参数顺序与 BuildWorker 约定一致: (log_queue, stop_event, cfg)
    log_queue 消息格式: ("cmd",命令行) / ("line", 文本) / ("error", 文本) / ("done", 退出码)
    """
    cmd = build_command(cfg)
    if not cmd:
        log_queue.put(("error", "找不到可用的 Python 解释器(需已安装 Nuitka)。"
                               "请安装 Python 后执行: pip install nuitka"))
        log_queue.put(("done", -1))
        return
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

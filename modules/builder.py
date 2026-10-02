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
    if os.name == "nt":
        for name in ("python", "python3", "py"):
            p = shutil.which(name)
            if p and p not in cands:
                cands.append(p)
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
    else:
        # Linux / macOS: 常见路径 + PATH
        for name in ("python3", "python", "python3.13", "python3.12", "python3.11"):
            p = shutil.which(name)
            if p and p not in cands:
                cands.append(p)
        for base in ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"):
            for name in ("python3", "python"):
                p = os.path.join(base, name)
                if p not in cands and os.path.isfile(p):
                    cands.append(p)
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

    # 控制台模式: --windows-console-mode / --enable-console 仅 Windows 有效
    if os.name == "nt":
        if cfg.get("console"):
            cmd.append("--enable-console")
        else:
            cmd.append("--windows-console-mode=disable")
    # Linux / macOS 上 --enable-console 无意义, Nuitka 默认带控制台

    # 图标: --windows-icon-from-ico 仅 Windows 有效; 跨平台用 --include-data-files 打进去
    if cfg.get("icon"):
        if os.name == "nt":
            cmd.append("--windows-icon-from-ico=%s" % cfg["icon"])
        # 把图标文件一并打进产物, 供运行时加载任务栏图标 (全平台通用)
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

    # Windows 元数据 (版本号/公司名/版权等) — 仅 Windows 有意义
    if os.name == "nt":
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


def _detect_qt_plugin_dirs(python_exe):
    """通过指定 Python 解释器探测 PyQt5/PyQt6/PySide2/PySide6 的插件目录

    适配多种安装布局: PyQt5/Qt5/plugins (新) vs PyQt5/plugins (旧)。
    返回已找到且含 platforms 子目录的绝对路径列表, 找不到返回 []。
    """
    probe = (
        "import os, importlib.util as u\n"
        "dirs=[]\n"
        "for b in ['PyQt5','PyQt6','PySide2','PySide6']:\n"
        "    if not u.find_spec(b): continue\n"
        "    try:\n"
        "        m=__import__(b); d=os.path.dirname(m.__file__)\n"
        "        for c in [os.path.join(d,'Qt5','plugins'),os.path.join(d,'Qt6','plugins'),os.path.join(d,'plugins')]:\n"
        "            if os.path.isdir(c) and os.path.isdir(os.path.join(c,'platforms')):\n"
        "                dirs.append(os.path.normpath(c)); break\n"
        "    except Exception: pass\n"
        "seen=set()\n"
        "for p in dirs:\n"
        "    n=os.path.normcase(os.path.abspath(p))\n"
        "    if n not in seen: seen.add(n); print(p)\n"
    )
    try:
        proc = subprocess.run(
            [python_exe, "-c", probe],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if proc.returncode == 0:
            return [l.strip() for l in proc.stdout.strip().splitlines() if l.strip()]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return []


def _build_env(cfg, log_queue):
    """构造 Nuitka 子进程的环境变量, 自动设置:
    - CL=/utf-8: MSVC UTF-8 编译 (仅 Windows)
    - NUITKA_CACHE_DIR: 重定向缓存到 output_dir/.nuitka_cache (规避沙箱/权限问题)
    - QT_PLUGIN_PATH / QT_QPA_PLATFORM_PLUGIN_PATH: 修复 PyQt5 等在新布局下的插件检测
    """
    env = os.environ.copy()
    if os.name == "nt":
        env["CL"] = "/utf-8"   # MSVC UTF-8 源文件编译

    # 1) Nuitka 缓存目录重定向 (NUITKA_CACHE_DIR 官方支持)
    if cfg:
        output_dir = (cfg.get("output_dir") or "").strip()
        if not output_dir:
            script_dir = os.path.dirname((cfg.get("script") or "").strip())
            if script_dir:
                output_dir = os.path.join(script_dir, "dist")
        if output_dir:
            cache_dir = os.path.join(os.path.abspath(output_dir), ".nuitka_cache")
            # Nuitka 4.2.x 在 NUITKA_CACHE_DIR 未预创建时, module-cache/ 等子目录会触发
            # FileNotFoundError (Nuitka 只 open 文件不 mkdir 父目录)。这里预创建根目录兜底。
            try:
                os.makedirs(cache_dir, exist_ok=True)
            except OSError:
                pass  # 权限或路径问题, 让 Nuitka 自己处理
            env["NUITKA_CACHE_DIR"] = cache_dir
            log_queue.put(("line", "[环境] Nuitka 缓存目录: %s" % cache_dir))

    # 2) Qt 插件目录自动探测 (修复 PyQt5/PySide 在 Python 3.13+ 上的布局问题)
    python_exe = resolve_python()
    if python_exe:
        qt_dirs = _detect_qt_plugin_dirs(python_exe)
        if qt_dirs:
            env["QT_PLUGIN_PATH"] = os.pathsep.join(qt_dirs)
            # QT_QPA_PLATFORM_PLUGIN_PATH 只取第一个 (一般只有一个绑定被实际使用)
            env["QT_QPA_PLATFORM_PLUGIN_PATH"] = qt_dirs[0]
            log_queue.put(("line", "[环境] Qt 插件目录: %s" % ", ".join(qt_dirs)))

    return env


def _mask_path_arg(arg):
    """命令回显脱敏: 路径参数只显示文件名, 避免日志泄露绝对路径。

    - 保留 --flag=value 里的 flag 名和等号 (自解释)
    - 值若包含路径分隔符, 只取最后一段 basename
    - 解释器路径 (cmd[0]) 也会被脱敏
    """
    if not arg:
        return arg
    # --flag=value 形式
    if "=" in arg and not arg.startswith("="):
        flag, _, val = arg.partition("=")
        # value 可能含路径
        if os.sep in val or "/" in val:
            val = os.path.basename(val.rstrip(os.sep).rstrip("/"))
        return "%s=%s" % (flag, val)
    # 独立路径参数 (脚本文件 / 解释器)
    if os.sep in arg or "/" in arg:
        return os.path.basename(arg)
    return arg


def run_build(log_queue, stop_event, cfg):
    """在线程中执行 Nuitka 打包, 日志逐行放入 log_queue

    参数顺序与 BuildWorker 约定一致: (log_queue, stop_event, cfg)
    log_queue 消息格式: ("cmd",命令行) / ("line", 文本) / ("error", 文本) / ("done", 退出码)
    """
    # === TOCTOU 二次校验 (真正使用文件的一方做最终确认) ===
    # UI 线程的 os.path.isfile 只是快路径预检; 从 UI 检查到 Nuitka 实际读文件之间
    # 有数百毫秒间隔, 本地攻击者可在窗口内替换目标脚本/图标。
    # 这里在后台线程启动后立即校验, 拿真实 I/O 时再确认一次。
    script = (cfg.get("script") or "").strip()
    if script and not os.path.isfile(script):
        log_queue.put(("error",
                       "打包被中止: 主脚本文件在启动时已不存在 (%s)。"
                       "可能被其他程序删除或移动。" % script))
        log_queue.put(("done", -1))
        return
    if cfg.get("icon") and not os.path.isfile(cfg["icon"]):
        log_queue.put(("error",
                       "图标文件在启动时已不存在 (%s), 请重新选择后重试。" % cfg["icon"]))
        log_queue.put(("done", -1))
        return

    cmd = build_command(cfg)
    if not cmd:
        log_queue.put(("error", "找不到可用的 Python 解释器(需已安装 Nuitka)。"
                               "请安装 Python 后执行: pip install nuitka"))
        log_queue.put(("done", -1))
        return
    # 回显脱敏: 去掉 PowerShell 前缀, 路径只显示 basename, 防止日志泄露项目位置
    masked_cmd = " ".join(_mask_path_arg(a) for a in cmd)
    log_queue.put(("cmd", masked_cmd))
    code = run_process(cmd, cwd=os.path.dirname(cfg.get("script") or "") or None,
                       log_queue=log_queue, stop_event=stop_event, cfg=cfg)
    log_queue.put(("done", code))


def _kill_process_tree(proc):
    """跨平台硬杀整个进程树。

    Nuitka 内部用 subprocess.Popen spawn scons / gcc / clang 等子进程,
    这些子进程继承了 stdout pipe 并在主进程 terminate/kill 后可能还在写。
    必须杀掉进程树 + 关闭 pipe, 才能让 pump 线程停止。
    """
    pid = proc.pid
    if os.name == "nt":
        # Windows: taskkill /T /F 杀进程树 (包括所有后代)
        # CREATE_NEW_PROCESS_GROUP 让子进程成为新进程组 leader, /T 能追踪所有后代
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        proc.kill()   # 兜底
    else:
        # POSIX: 假设 start_new_session=True, 进程组 leader = proc.pid
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, AttributeError, OSError):
            proc.kill()
    # 立刻关闭 stdout pipe, 让 pump 线程的 for-in 迭代器停止
    try:
        proc.stdout.close()
    except Exception:
        pass
    # 等待 2 秒确保释放资源
    try:
        proc.wait(timeout=2)
    except (subprocess.TimeoutExpired, OSError):
        pass


def run_process(cmd, cwd, log_queue, stop_event, cfg=None):
    """启动子进程, 逐行输出日志到 log_queue, 支持通过 stop_event 取消

    返回退出码: 0 成功, -1 启动失败, -2 用户取消
    """
    try:
        creationflags = subprocess.CREATE_NO_WINDOW
        if os.name == "nt":
            # CREATE_NEW_PROCESS_GROUP 让子进程成为新进程组 leader,
            # 方便 taskkill /T 追踪全部后代 (scons, gcc 等)
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags if os.name == "nt" else 0,
            start_new_session=(os.name != "nt"),
            cwd=cwd or None,
            env=_build_env(cfg, log_queue),
        )
    except Exception as exc:
        log_queue.put(("error", "无法启动命令: %s" % exc))
        return -1

    def pump():
        try:
            for line in proc.stdout:
                log_queue.put(("line", line.rstrip("\n")))
        except (ValueError, OSError):
            # stdout.close() 后迭代器会抛 ValueError / OSError, 忽略
            pass
        except Exception:
            pass

    threading.Thread(target=pump, daemon=True).start()

    while proc.poll() is None:
        if stop_event.wait(0.2):
            _kill_process_tree(proc)
            log_queue.put(("line", "[已取消]"))
            return -2
    return proc.returncode

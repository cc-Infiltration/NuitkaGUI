# -*- coding: utf-8 -*-
"""环境依赖检查: Nuitka 与 C 编译器 (MinGW64)。

- run_env_check(): 完整环境检查, 返回 [(名称, 状态, 详情, 修复建议), ...]。
   状态: "ok" 正常 / "warn" 警告(可继续) / "error" 失败(需修复)。
- check_nuitka(): 检测 Nuitka 版本。
- check_compiler(): 检测系统 gcc / MSVC / Nuitka 缓存及常见位置的 MinGW64。
- run_mingw_download(): 通过一次极简编译触发 Nuitka 自动下载 MinGW64。
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

from .builder import resolve_python, run_process, _mask_path_arg

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_VERSION_RE = re.compile(r"^\d+(\.\d+)+")

# 常见的 MinGW64 安装位置(部分含版本子目录, 需要浅层探测)
_MINGW_COMMON = [
    r"C:\msys64\mingw64\bin\gcc.exe",
    r"C:\msys2\mingw64\bin\gcc.exe",
    r"C:\mingw64\bin\gcc.exe",
    r"C:\MinGW\bin\gcc.exe",
    r"C:\TDM-GCC-64\bin\gcc.exe",
    r"C:\Program Files\mingw-w64",
    r"C:\Program Files (x86)\mingw-w64",
    r"C:\msys64",
    r"C:\msys2",
]


def _probe(cmd, timeout=20):
    """运行命令并捕获输出; 命令不存在或超时返回 None。"""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _first_line(text):
    text = (text or "").strip()
    return text.splitlines()[0].strip() if text.splitlines() else ""


def _parse_version(text):
    """从文本中提取类似 4.1.3 的版本号, 找不到返回 None。"""
    text = (text or "").strip()
    for line in text.splitlines():
        m = _VERSION_RE.search(line)
        if m:
            return m.group(0)
    return None


def check_python():
    """返回 Python 版本字符串。"""
    return sys.version.split()[0]


def check_upx():
    """检测 UPX 是否可用 (PATH 或常见安装位置)。"""
    if shutil.which("upx"):
        return True
    if os.name == "nt":
        for cand in (r"C:\upx\upx.exe",
                     r"C:\Program Files\upx\upx.exe",
                     r"C:\Program Files (x86)\upx\upx.exe"):
            if os.path.isfile(cand):
                return True
    else:
        for cand in ("/usr/bin/upx", "/usr/local/bin/upx", "/opt/homebrew/bin/upx"):
            if os.path.isfile(cand):
                return True
    return False


def python_requires_msvc():
    """Windows 上 Python 3.13+ 需要 MSVC 编译器 (Nuitka 不支持 MinGW64);
    Linux / macOS 上 Nuitka 默认使用系统 gcc/clang, 不强制 MSVC。"""
    return os.name == "nt" and sys.version_info >= (3, 13)


def _find_cl_in(base):
    """在 MSVC 版本目录下查找最新的 cl.exe (Hostx64/x64)"""
    if not os.path.isdir(base):
        return None
    try:
        versions = [d for d in os.listdir(base)
                    if os.path.isdir(os.path.join(base, d))]
    except OSError:
        return None
    for ver in sorted(versions, reverse=True):
        for sub in ("bin/Hostx64/x64/cl.exe", "bin/cl.exe"):
            cand = os.path.join(base, ver, *sub.split("/"))
            if os.path.isfile(cand):
                return cand
    return None


def find_msvc():
    """检测是否安装 MSVC (Visual Studio / Build Tools)

    仅 Windows 有效; Linux/macOS 上 Nuitka 用系统 gcc/clang, 直接返回 [].
    """
    if os.name != "nt":
        return []
    found = []
    prog_files = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]
    # vswhere
    for base in prog_files:
        if not base:
            continue
        vs = os.path.join(base, "Microsoft Visual Studio", "Installer", "vswhere.exe")
        if os.path.isfile(vs):
            try:
                proc = subprocess.run(
                    [vs, "-products", "*",
                     "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                     "-property", "installationPath"],
                    capture_output=True, text=True, timeout=15,
                    creationflags=CREATE_NO_WINDOW)
                for line in (proc.stdout or "").splitlines():
                    line = line.strip()
                    if line:
                        cl = _find_cl_in(os.path.join(line, "VC", "Tools", "MSVC"))
                        if cl:
                            found.append(cl)
            except (OSError, subprocess.TimeoutExpired):
                pass
    # 常见安装路径
    base_dir = prog_files[0] or r"C:\Program Files (x86)"
    for year in ("2019", "2022"):
        for edition in ("Community", "Professional", "Enterprise", "BuildTools"):
            cl = _find_cl_in(os.path.join(
                base_dir, "Microsoft Visual Studio", year, edition,
                "VC", "Tools", "MSVC"))
            if cl:
                found.append(cl)
    # PATH
    cl = shutil.which("cl")
    if cl:
        found.append(cl)
    # 去重保序
    seen = set()
    uniq = []
    for p in found:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def check_nuitka():
    """检测 Nuitka 是否可运行, 返回 (是否可用, 版本/描述)

    优先读取安装元数据(快速且无副作用); 回退执行 nuitka --version,
    只要输出中包含版本号(即使因缓存目录权限输出 FATAL)也视为已安装
    """
    try:
        from importlib.metadata import version
        ver = version("nuitka")
        if ver:
            return True, ver
    except Exception:
        pass
    proc = _probe([sys.executable, "-m", "nuitka", "--version"])
    if proc and proc.stdout:
        ver = _parse_version(proc.stdout)
        if ver:
            return True, ver
    return False, "未检测到"


def _walk_limited(root, max_depth=3):
    """限制遍历深度的 os.walk, 避免扫描整个缓存目录"""
    root = root.rstrip(os.sep)
    depth = root.count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        yield dirpath, dirnames, filenames
        if dirpath.count(os.sep) - depth >= max_depth:
            dirnames[:] = []


def _cache_roots():
    """Nuitka 下载缓存的候选根目录"""
    roots = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        app = os.environ.get("APPDATA")
        if local:
            roots.append(os.path.join(local, "Nuitka"))
        if app:
            roots.append(os.path.join(app, "Nuitka"))
    roots.append(os.path.join(os.path.expanduser("~"), ".cache", "Nuitka"))
    return [r for r in roots if r and os.path.isdir(r)]


def _find_mingw_in_cache():
    """在 Nuitka 下载缓存中查找已下载的 MinGW64 (gcc.exe)"""
    found = []
    for root in _cache_roots():
        hit = None
        for dirpath, _dirnames, filenames in _walk_limited(root):
            if "gcc.exe" in filenames:
                hit = os.path.join(dirpath, "gcc.exe")
                break
        if hit:
            found.append(hit)
    return found


def _find_mingw_common():
    """在常见安装位置查找 gcc.exe(浅层探测, 兼容版本子目录)"""
    found = []
    for cand in _MINGW_COMMON:
        if os.path.isfile(cand):
            found.append(cand)
        elif os.path.isdir(cand):
            # 部分安装目录下还有一层版本子目录 (如 .../mingw-w64/x86_64-.../mingw64/bin)
            try:
                for sub in os.listdir(cand):
                    sub = os.path.join(cand, sub)
                    if os.path.isdir(sub):
                        cand2 = os.path.join(sub, "mingw64", "bin", "gcc.exe")
                        if os.path.isfile(cand2):
                            found.append(cand2)
                            break
            except OSError:
                pass
    return found


MSVC_HINT = ("请安装 Microsoft C++ Build Tools:\n"
             "    winget install Microsoft.VisualStudio.2022.BuildTools\n"
             "或访问 https://visualstudio.microsoft.com/downloads/ 安装「使用 C++ 的桌面开发」工作负载。")

GCC_LINUX_HINT = ("请安装 GNU C 编译器:\n"
                  "    Debian/Ubuntu:  sudo apt install build-essential\n"
                  "    Fedora/RHEL:    sudo dnf install gcc gcc-c++\n"
                  "    Arch:           sudo pacman -S base-devel\n"
                  "    macOS (Homebrew): brew install gcc (或自带 clang)")


def _probe_compiler_version(cmd_list):
    """运行 --version 并取首行, 失败返回空串。"""
    proc = _probe(cmd_list, timeout=10)
    return _first_line(proc.stdout) if proc else ""


def check_compiler():
    """检测 C 编译器。

    返回 (是否可用, [(名称, 状态, 详情, 修复建议), ...])。

    Windows: Python <= 3.12 用 gcc / MSVC / MinGW64 任一; Python 3.13+ 强制 MSVC。
    Linux / macOS: gcc 或 clang 任一即可 (Nuitka 默认使用), 无 MinGW/MSVC 概念。
    """
    results = []
    ok = False

    # --- Linux / macOS 分支 ---
    if os.name != "nt":
        # gcc
        gcc = shutil.which("gcc")
        if gcc:
            ver = _probe_compiler_version([gcc, "--version"])
            results.append(("系统 gcc", "ok", "%s (%s)" % (gcc, ver or "版本未知"), ""))
            ok = True
        else:
            results.append(("系统 gcc", "error", "未检测到", GCC_LINUX_HINT))

        # clang (gcc 的替代品, 并列列出)
        clang = shutil.which("clang")
        if clang:
            ver = _probe_compiler_version([clang, "--version"])
            results.append(("系统 clang", "ok", "%s (%s)" % (clang, ver or "版本未知"), ""))
            ok = True
        else:
            results.append(("系统 clang", "warn", "未加入 PATH (gcc 可用即可)", ""))

        return ok, results

    # --- Windows 分支 ---
    msvc_required = python_requires_msvc()

    gcc = shutil.which("gcc")
    if gcc:
        ver = _probe_compiler_version([gcc, "--version"])
        results.append(("系统 gcc", "ok", "%s (%s)" % (gcc, ver or "版本未知"), ""))
        ok = True
    else:
        results.append(("系统 gcc", "warn", "未加入 PATH (可选, 不强制)", ""))

    msvc = find_msvc()
    if msvc:
        results.append(("MSVC", "ok", msvc[0], ""))
        ok = True
    else:
        results.append(("MSVC", "error" if msvc_required else "warn",
                        "未检测到", MSVC_HINT if msvc_required else ""))

    if msvc_required:
        # Python 3.13+ 下不检测 MinGW64 (Nuitka 不支持), 避免出现多余提示
        pass
    else:
        mingw_paths = _find_mingw_in_cache() + _find_mingw_common()
        if mingw_paths:
            results.append(("MinGW64", "ok", mingw_paths[0], ""))
            ok = True
        else:
            results.append(("MinGW64", "error", "未找到; 首次打包时 Nuitka 会自动下载",
                            "点击「下载 MinGW64」预下载, 或直接开始打包(已自动确认下载)"))

    return ok, results


def run_env_check():
    """完整环境检查。

    返回 [(名称, 状态, 详情, 修复建议), ...]。状态: ok / warn / error。
    整体通过 = 不包含 error 项。
    """
    items = []
    items.append(("Python 版本", "ok", check_python(), ""))

    ok_n, ver = check_nuitka()
    if ok_n:
        hint = ""
        try:
            nums = tuple(int(x) for x in ver.split(".")[:2])
            if nums < (2, 0):
                hint = "建议升级: pip install -U nuitka"
        except ValueError:
            pass
        items.append(("Nuitka", "ok", ver, hint))
    else:
        items.append(("Nuitka", "error", "未检测到",
                      "请安装: pip install nuitka (官方源: pip install nuitka)"))

    ok_c, compiler_results = check_compiler()
    for name, status, detail, hint in compiler_results:
        items.append((name, status, detail, hint))

    return items


def run_mingw_download(log_queue, stop_event):
    """预下载编译器 — Linux/macOS 不需要 MinGW, 直接提示装 gcc/clang。"""
    if os.name != "nt":
        log_queue.put(("error", "Linux / macOS 使用系统 gcc/clang 即可编译, 无需 MinGW64。"))
        log_queue.put(("error", GCC_LINUX_HINT))
        log_queue.put(("mingw_done", -1))
        return
    if python_requires_msvc():
        log_queue.put(("error", "Python %s 不支持自动下载 MinGW64 编译器 (Nuitka 限制)。"
                       % sys.version.split()[0]))
        log_queue.put(("error", "请安装 Microsoft C++ Build Tools: "
                              "winget install Microsoft.VisualStudio.2022.BuildTools"))
        log_queue.put(("mingw_done", -1))
        return
    python = resolve_python()
    if not python:
        log_queue.put(("error", "找不到可用的 Python 解释器(需已安装 Nuitka)。"))
        log_queue.put(("mingw_done", -1))
        return
    tmp = tempfile.mkdtemp(prefix="nuitka_mingw_")
    try:
        probe = os.path.join(tmp, "probe.py")
        out = os.path.join(tmp, "out")
        os.makedirs(out, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as f:
            f.write("print('compiler ok')\n")
        cmd = [
            python, "-m", "nuitka",
            "--module", "--mingw64", "--nofollow-imports",
            "--assume-yes-for-downloads",
            "--output-dir=%s" % out,
            probe,
        ]
        log_queue.put(("cmd", " ".join(_mask_path_arg(a) for a in cmd)))
        code = run_process(cmd, cwd=tmp, log_queue=log_queue, stop_event=stop_event)
        if code == 0:
            log_queue.put(("ok", "MinGW64 下载并验证完成, 现在可以直接打包了。"))
        elif code == -2:
            log_queue.put(("line", "[已取消 MinGW64 下载]"))
        else:
            log_queue.put(("error", "MinGW64 下载/验证失败, 请检查网络后重试。"))
        log_queue.put(("mingw_done", code))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

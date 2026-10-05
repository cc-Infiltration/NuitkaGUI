# -*- coding: utf-8 -*-
"""环境依赖检查: Nuitka 与 C 编译器 (MinGW64)。

- run_env_check(): 完整环境检查, 返回 [(名称, 状态, 详情, 修复建议), ...]。
   状态: "ok" 正常 / "warn" 警告(可继续) / "error" 失败(需修复)。
- check_nuitka(): 检测 Nuitka 版本。
- check_compiler(): 检测系统 gcc / MSVC / Nuitka 缓存及常见位置的 MinGW64。
- run_mingw_download(): 通过一次极简编译触发 Nuitka 自动下载 MinGW64。
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from .builder import resolve_python, run_process, _mask_path_arg

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
_VERSION_RE = re.compile(r"^\d+(\.\d+)+")

# MSVC 内部版本号 → 发布年份/名称
# vswhere 的 catalog.productLineVersion 就是内部版本: 18 → 2026, 17 → 2022 等
_MSVC_NAME_MAP = {
    "18": "Visual Studio 2026",
    "17": "Visual Studio 2022",
    "16": "Visual Studio 2019",
    "15": "Visual Studio 2017",
    "14": "Visual Studio 2015",
}

# MSVC cl.exe 版本号 → MSVC 发布年份 (cl.exe --version 输出)
# 例如 Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35207 → MSVC 2022
_CL_VERSION_MAP = [
    (19, 40, "MSVC 2022+"),   # 19.40+ = VS 2022 v17.8+ / VS 2026
    (19, 30, "MSVC 2022"),    # 19.30 - 19.39 = VS 2022
    (19, 20, "MSVC 2019"),    # 19.20 - 19.29 = VS 2019
    (19, 10, "MSVC 2017"),    # 19.10 - 19.19 = VS 2017
    (19, 0, "MSVC 2015"),    # 19.00 = VS 2015
]

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
    Linux / macOS 上 Nuitka 默认使用系统 gcc/clang, 不强制 MSVC。
    """
    return os.name == "nt" and sys.version_info >= (3, 13)


def _annotate_cl(cl_path):
    """给 cl.exe 查版本号 + 发行名。返回 (path, msc_ver_str, release_name)。"""
    msc_ver = ""
    release = "MSVC"
    try:
        # cl.exe 在 Windows 上输出系统 OEM 编码 (中文系统是 CP936),
        # 不用 text=True 自动 UTF-8, 手动用 errors=replace 防止解码崩溃
        proc = subprocess.run([cl_path], capture_output=True, timeout=5,
                              creationflags=CREATE_NO_WINDOW)
        out = (proc.stderr or proc.stdout or b"").decode(
            "utf-8", errors="replace") + (proc.stdout or b"").decode(
            "utf-8", errors="replace")
        m = re.search(r"Version\s+(\d+)\.(\d+)\.(\d+)", out)
        if m:
            major, minor = int(m.group(1)), int(m.group(2))
            msc_ver = f"{major}.{minor}"
            for cl_maj, cl_min, name in _CL_VERSION_MAP:
                if (major > cl_maj) or (major == cl_maj and minor >= cl_min):
                    release = name
                    break
    except (OSError, subprocess.TimeoutExpired):
        pass
    return (cl_path, msc_ver, release)


def _vswhere_json():
    """调用 vswhere 并解析 JSON, 返回 vs 实例列表。失败返回 []。"""
    if os.name != "nt":
        return []
    # vswhere 的位置: 跟随最新的 VS 安装, 都在 ProgramFiles(x86)
    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    vswhere = os.path.join(pf86, "Microsoft Visual Studio", "Installer", "vswhere.exe")
    if not os.path.isfile(vswhere):
        return []
    try:
        proc = subprocess.run(
            [vswhere, "-products", "*",
             "-format", "json", "-utf8"],
            capture_output=True, timeout=15,
            creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0 or not proc.stdout:
            return []
        data = json.loads(proc.stdout)
        return data if isinstance(data, list) else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []


def find_msvc(extra_dirs=None):
    """检测所有 MSVC 安装。

    检测顺序:
      1) vswhere JSON (最权威, 能找到自定义路径安装)
      2) 硬编码路径 (覆盖老版本 vswhere 扫不到的情况)
      3) PATH 里的 cl
      4) 用户传入的 extra_dirs

    两阶段执行:
      Phase 1 (串行, 快): 收集所有 cl.exe 路径 + 元数据 (display/安装根), 不跑子进程
      Phase 2 (并行, 慢): 批量跑版本探测 (最多 6 个并发子进程)

    返回 [{"path": cl_path, "version": "19.44", "release": "MSVC 2022",
           "display": "Visual Studio 2026 (18.10) — D:\\...", "首选": True/False}, ...]
    按版本降序, 最新的排第一个并标记 "首选"。
    """
    if os.name != "nt":
        return []

    # ---- Phase 1: 收集所有 cl.exe (不跑子进程, 纯 os.path.isfile) ----
    # 内部 _collect_cl_paths 是 _find_cl_in 的精简版: 只收集路径不跑 _annotate_cl
    def _collect_cl_paths(base):
        """纯路径收集: 从 base 下找到 cl.exe, 返回 (cl_path, None, None) 或 None。"""
        if not base or not os.path.isdir(base):
            return None
        try:
            versions = sorted(
                [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))],
                reverse=True)
        except OSError:
            return None
        for ver in versions:
            for sub in ("bin/Hostx64/x64/cl.exe", "bin/Hostx64/x86/cl.exe", "bin/cl.exe"):
                cand = os.path.join(base, ver, *sub.split("/"))
                if os.path.isfile(cand):
                    return cand
        for sub in ("bin/Hostx64/x64/cl.exe", "bin/cl.exe", "cl.exe"):
            cand = os.path.join(base, *sub.split("/"))
            if os.path.isfile(cand):
                return cand
        return None

    candidates = []  # [(cl_path, display, install_path)]
    seen_paths = set()

    # 1) vswhere JSON
    for inst in _vswhere_json():
        if not inst.get("isComplete"):
            continue
        install_path = inst.get("installationPath")
        if not install_path:
            continue
        msvc_tools = os.path.join(install_path, "VC", "Tools", "MSVC")
        cl_path = _collect_cl_paths(msvc_tools) or _collect_cl_paths(install_path)
        if not cl_path:
            continue
        norm = os.path.normpath(cl_path).lower()
        if norm in seen_paths:
            continue
        seen_paths.add(norm)
        product_line = inst.get("catalog", {}).get("productLineVersion", "")
        vs_name = _MSVC_NAME_MAP.get(
            str(product_line), inst.get("displayName", "Visual Studio"))
        version_str = inst.get("catalog", {}).get(
            "productDisplayVersion", inst.get("installationVersion", ""))
        candidates.append((cl_path, f"{vs_name} ({version_str})", install_path))

    # 2) 硬编码路径兜底
    prog_files = [os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")]
    for base in prog_files:
        if not base:
            continue
        for year in ("2015", "2017", "2019", "2022"):
            for edition in ("Community", "Professional", "Enterprise", "BuildTools"):
                msvc_tools = os.path.join(
                    base, "Microsoft Visual Studio", year, edition,
                    "VC", "Tools", "MSVC")
                cl_path = _collect_cl_paths(msvc_tools)
                if not cl_path:
                    continue
                norm = os.path.normpath(cl_path).lower()
                if norm in seen_paths:
                    continue
                seen_paths.add(norm)
                candidates.append((
                    cl_path, f"Visual Studio {year} ({edition})",
                    os.path.dirname(os.path.dirname(msvc_tools))))

    # 3) PATH
    cl_on_path = shutil.which("cl")
    if cl_on_path:
        norm = os.path.normpath(cl_on_path).lower()
        if norm not in seen_paths:
            seen_paths.add(norm)
            candidates.append((cl_on_path, "PATH 中的 cl.exe",
                               os.path.dirname(os.path.dirname(cl_on_path))))

    # 4) 自定义目录
    for d in (extra_dirs or []):
        if not d:
            continue
        cl_path = _collect_cl_paths(d)
        if not cl_path:
            continue
        norm = os.path.normpath(cl_path).lower()
        if norm in seen_paths:
            continue
        seen_paths.add(norm)
        candidates.append((cl_path, f"自定义目录: {d}", d))

    # ---- Phase 2: 批量并行跑版本探测 ----
    if not candidates:
        return []
    all_cl_paths = [c[0] for c in candidates]
    annot_map = _batch_annotate_cl(all_cl_paths)  # {path: (msc_ver, release)}

    # 组装结果
    results = []
    for cl_path, display, install_path in candidates:
        msc_ver, release = annot_map.get(cl_path, ("", "MSVC"))
        results.append({
            "path": cl_path,
            "version": msc_ver,
            "release": release,
            "display": display,
            "install_path": install_path,
        })

    # 按版本降序排序
    def _sort_key(r):
        try:
            return tuple(int(x) for x in r["version"].split("."))
        except (ValueError, AttributeError):
            return (0, 0)
    results.sort(key=_sort_key, reverse=True)

    # 标记首选
    if results:
        results[0]["preferred"] = True
        for r in results[1:]:
            r["preferred"] = False
    return results


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


# 合法 Nuitka 插件名: 小写字母/数字开头, 仅含小写字母、数字、连字符
# 插件名最终进入命令行 --enable-plugin=<name>, 必须拒绝路径分隔符、空格、
# 引号等一切非常量字符, 防命令/路径注入
_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# 单个插件源文件大小上限, 防止异常超大文件拖慢启动解析
_PLUGIN_SCAN_LIMIT_BYTES = 1024 * 1024


def _nuitka_package_dir():
    """定位 nuitka 包目录; 未安装返回 None。

    用 find_spec 只查询不导入, 避免执行 nuitka/__init__.py。
    """
    try:
        spec = importlib.util.find_spec("nuitka")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for loc in spec.submodule_search_locations:
        if loc and os.path.isdir(loc):
            return loc
    return None


def _extract_plugin_names(source):
    """AST 静态提取源码中的 plugin_name 字符串常量。

    只解析语法树、读取字符串字面量, 绝不 import/exec 插件模块 —
    插件文件内容不可信时也不会执行任何代码。语法错误返回空集合。
    """
    names = set()
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return names
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == "plugin_name"):
                continue
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                name = value.value.strip()
                if _PLUGIN_NAME_RE.match(name):
                    names.add(name)
    return names


def list_nuitka_plugins():
    """自动发现当前 Nuitka 安装的全部内置插件名, 返回 set。

    安全设计:
    - 只静态解析 nuitka/plugins/standard/*.py 的 plugin_name (AST),
      不 import 任何插件模块, 不执行第三方代码
    - 插件名白名单校验 (小写字母/数字/连字符), 防命令与路径注入
    - 不跟随符号链接; 真实路径必须仍在 standard 目录内 (防链接逃逸)
    - 跳过超大文件与解析失败的单文件, 不影响其余插件发现
    Nuitka 未安装或目录异常时返回空集合 (调用方回退内置列表)。
    """
    nuitka_dir = _nuitka_package_dir()
    if not nuitka_dir:
        return set()
    std_dir = os.path.join(nuitka_dir, "plugins", "standard")
    if not os.path.isdir(std_dir):
        return set()
    try:
        std_real = os.path.realpath(std_dir)
        entries = list(os.scandir(std_dir))
    except OSError:
        return set()
    names = set()
    for entry in entries:
        try:
            if not entry.name.endswith(".py") or entry.name == "__init__.py":
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            entry_real = os.path.realpath(entry.path)
            try:
                inside = os.path.commonpath([std_real, entry_real]) == std_real
            except ValueError:  # 跨盘符等, 视为逃逸
                inside = False
            if not inside:
                continue
            if entry.stat(follow_symlinks=False).st_size > _PLUGIN_SCAN_LIMIT_BYTES:
                continue
            with open(entry.path, "r", encoding="utf-8", errors="replace") as f:
                source = f.read()
        except OSError:
            continue
        names |= _extract_plugin_names(source)
    return names


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


def _batch_probe_versions(paths, args=("--version",), timeout=8, max_workers=6):
    """批量并行跑版本探测, 返回 {path: version_str} 字典。

    最多 max_workers 个并行子进程, 防止系统里装了 10 个编译器时同时起 10 个进程。
    """
    results = {}
    if not paths:
        return results
    workers = min(max_workers, len(paths))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_probe, [p] + list(args), timeout=timeout): p
                   for p in paths}
        for fut in as_completed(futures):
            p = futures[fut]
            proc = fut.result()
            ver = _first_line(proc.stdout) if proc else ""
            results[p] = ver
    return results


def _batch_annotate_cl(cl_paths, max_workers=6):
    """批量并行探测 cl.exe 版本, 返回 {path: (msc_ver_str, release_name)}。"""
    results = {}
    if not cl_paths:
        return results
    workers = min(max_workers, len(cl_paths))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_annotate_cl, p): p for p in cl_paths}
        for fut in as_completed(futures):
            path = futures[fut]
            try:
                _p, msc_ver, release = fut.result()
                results[path] = (msc_ver, release)
            except Exception:
                results[path] = ("", "MSVC")
    return results


def _find_all_gcc_windows():
    """Windows 上尽可能多地找到 gcc.exe / MinGW64。

    两阶段执行:
      Phase 1 (串行, 快): 收集所有 gcc.exe 路径 (os.path.isfile + registry, 无子进程)
      Phase 2 (并行, 慢): 批量跑 gcc --version (最多 6 个并发)

    扫描来源: PATH / Nuitka 缓存 / _MINGW_COMMON / 注册表 Uninstall。
    返回 [{"path": ..., "source": "PATH|Nuitka缓存|...", "version": "...",
           "distro": "MinGW64|MSYS2|TDM-GCC|..."}, ...] 按版本降序。
    """
    # ---- Phase 1: 收集所有 gcc.exe (纯文件系统, 不跑子进程) ----
    candidates = []  # [(gcc_path, source, distro_hint)]
    seen_paths = set()

    def _collect(path, source, distro_hint=""):
        if not path or not os.path.isfile(path):
            return
        norm = os.path.normpath(path).lower()
        if norm in seen_paths:
            return
        seen_paths.add(norm)
        candidates.append((path, source, distro_hint))

    # 1) PATH
    for g in ("gcc", "x86_64-w64-mingw32-gcc"):
        p = shutil.which(g)
        if p:
            _collect(p, "PATH")

    # 2) Nuitka 下载缓存
    for p in _find_mingw_in_cache():
        _collect(p, "Nuitka 缓存")

    # 3) _MINGW_COMMON
    for p in _find_mingw_common():
        _collect(p, "常见安装位置")

    # 4) 注册表 Uninstall
    try:
        import winreg
        for hive, view in [(winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                           (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
                           (winreg.HKEY_CURRENT_USER, 0)]:
            try:
                k = winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                                   access=winreg.KEY_READ | view)
            except OSError:
                continue
            try:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                        i += 1
                    except OSError:
                        break
                    sub_low = sub.lower()
                    if not any(k in sub_low for k in ("mingw", "msys", "tdm", "gcc")):
                        continue
                    try:
                        sk = winreg.OpenKey(k, sub)
                        install_loc, _ = winreg.QueryValueEx(sk, "InstallLocation")
                        winreg.CloseKey(sk)
                        gcc_cand = os.path.join(install_loc, "mingw64", "bin", "gcc.exe")
                        if os.path.isfile(gcc_cand):
                            _collect(gcc_cand, f"注册表: {sub}")
                    except OSError:
                        pass
                winreg.CloseKey(k)
            except OSError:
                pass
    except ImportError:
        pass

    # ---- Phase 2: 批量并行跑版本探测 ----
    if not candidates:
        return []
    all_paths = [c[0] for c in candidates]
    ver_map = _batch_probe_versions(all_paths, args=("--version",), max_workers=6)

    # 推断发行版
    def _guess_distro(path, hint=""):
        if hint:
            return hint
        low = path.lower()
        if "msys64" in low or "msys2" in low:
            return "MSYS2 MinGW64"
        if "tdm" in low:
            return "TDM-GCC"
        if "mingw64" in low:
            return "MinGW64"
        if "mingw" in low:
            return "MinGW"
        if "mingw-w64" in low:
            return "MinGW-w64"
        return "MinGW64"

    results = []
    for gcc_path, source, distro_hint in candidates:
        ver = _first_line(ver_map.get(gcc_path, ""))
        results.append({
            "path": gcc_path,
            "source": source,
            "version": ver,
            "distro": _guess_distro(gcc_path, distro_hint),
        })

    # 按版本降序
    def _sort_key(r):
        m = _VERSION_RE.search(r.get("version", ""))
        if m:
            try:
                return tuple(int(x) for x in m.group(0).split("."))
            except ValueError:
                pass
        return (0,)
    results.sort(key=_sort_key, reverse=True)
    return results


def check_compiler(extra_dirs=None):
    """检测 C 编译器。

    extra_dirs: 用户手动指定的编译器搜索目录列表。

    返回 (是否可用, [(名称, 状态, 详情, 修复建议), ...])。

    Windows: Python <= 3.12 用 gcc / MSVC / MinGW64 任一; Python 3.13+ 强制 MSVC。
    Linux / macOS: gcc 或 clang 任一即可 (Nuitka 默认使用), 无 MinGW/MSVC 概念。
    """
    results = []
    ok = False

    # --- Linux / macOS 分支 ---
    if os.name != "nt":
        # gcc (可能多版本, 通过不同后缀区分)
        gcc_any = False
        for suffix in ("", "-14", "-13", "-12", "-11", "-10", "-9"):
            gcc = shutil.which("gcc" + suffix)
            if gcc:
                ver = _probe_compiler_version([gcc, "--version"])
                label = "系统 gcc" + (suffix if suffix else "")
                results.append((label, "ok", "%s (%s)" % (gcc, ver or "版本未知"), ""))
                ok = True
                gcc_any = True
        if not gcc_any:
            results.append(("系统 gcc", "error", "未检测到", GCC_LINUX_HINT))

        # clang
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

    # MSVC (多版本)
    msvc_list = find_msvc(extra_dirs=extra_dirs)
    if msvc_list:
        for i, m in enumerate(msvc_list):
            tag = " ★首选" if m.get("preferred") else ""
            detail = f"{m['display']}{tag}\n  cl: {m['path']}"
            if m["version"]:
                detail += f"\n  编译器版本: cl {m['version']}"
            status = "ok"
            results.append(("MSVC", status, detail, ""))
            ok = True
    else:
        results.append(("MSVC", "error" if msvc_required else "warn",
                        "未检测到", MSVC_HINT if msvc_required else ""))

    # GCC/MinGW (多版本) — 仅在 Python < 3.13 下有意义
    if msvc_required:
        pass
    else:
        gcc_list = _find_all_gcc_windows()
        # 也搜用户 extra_dirs 里的 gcc
        for d in (extra_dirs or []):
            if not d:
                continue
            for sub in ("gcc.exe", "bin/gcc.exe", "mingw64/bin/gcc.exe"):
                cand = os.path.join(d, *sub.split("/"))
                if os.path.isfile(cand) and not any(
                        os.path.normpath(r["path"]) == os.path.normpath(cand)
                        for r in gcc_list):
                    gcc_list.append({
                        "path": cand, "source": f"自定义目录: {d}",
                        "version": _first_line(
                            _probe_compiler_version([cand, "--version"])),
                        "distro": "MinGW64",
                    })
        if gcc_list:
            for i, g in enumerate(gcc_list):
                tag = "" if i > 0 else " (首选)"
                ver_info = f", {g['version'][:60]}" if g["version"] else ""
                results.append((
                    f"{g['distro']}{tag}", "ok",
                    f"{g['path']}{ver_info}\n  来源: {g['source']}", ""))
                ok = True
        else:
            results.append(("MinGW64", "error", "未找到; 首次打包时 Nuitka 会自动下载",
                            "点击「下载 MinGW64」预下载, 或直接开始打包(已自动确认下载)"))

    return ok, results


def run_env_check(extra_dirs=None):
    """完整环境检查。

    extra_dirs: 用户手动指定的编译器搜索目录列表 (如 config['custom_compiler_dirs'])。

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

    ok_c, compiler_results = check_compiler(extra_dirs=extra_dirs)
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

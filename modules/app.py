# -*- coding: utf-8 -*-
#Nuitka 打包工具 GUI 主界面 (PySide6)

import math
import os
import re
import sys
import threading

from PySide6.QtCore import (
    QElapsedTimer, QObject, QPoint, QPointF, QRegularExpression, Qt, QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QPainter, QPolygonF,
    QRegularExpressionValidator, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QGroupBox, QHeaderView,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QSpinBox,
    QTableWidget, QTableWidgetItem, QTabWidget, QToolButton, QToolTip,
    QVBoxLayout, QWidget,
)

from . import deps
from .builder import build_command, run_build, stop_active_builds
from .config import DEFAULT_CONFIG, DEFAULT_SCRIPT, load_config, save_config


def _load_qss(name):
    """加载 styles 目录下的主题样式文件(标准 .qss 后缀)。

    源码运行: styles/ 位于项目根目录(app.py 在 modules/ 下)。
    打包产物: styles/*.qss 由构建命令通过 --include-data-files 打进产物
    (与 sys.executable 同目录的 styles/ 子目录)。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(here, "styles", name),
        os.path.join(os.getcwd(), "styles", name),
    ]
    if sys.executable:
        candidates.append(
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                         "styles", name))
    for p in candidates:
        try:
            with open(p, encoding="utf-8") as f:
                return f.read()
        except OSError:
            continue
    return ""


APP_QSS = _load_qss("light.qss")
APP_DARK_QSS = _load_qss("dark.qss")

# Nuitka 4.2.2 全部 37 个内置插件 (来源: nuitka/plugins/standard/*.py 的 plugin_name)
# 按用途分组展示; 插件名区分大小写, 必须小写
PLUGIN_GROUPS = (
    ("GUI / 图形界面", (
        ("pyside6", "PySide6 (Qt for Python) 应用"),
        ("pyside2", "PySide2 (Qt for Python) 应用"),
        ("pyqt6", "PyQt6 应用"),
        ("pyqt5", "PyQt5 应用"),
        ("tk-inter", "Tkinter 界面 (自动包含 TCL 运行库)"),
        ("kivy", "Kivy 多媒体应用"),
        ("glfw", "GLFW OpenGL 窗口程序"),
        ("pywebview", "pywebview 轻量级网页界面"),
        ("gi", "GTK / PyGObject (gi) 应用"),
        ("pmw-freezer", "Pmw (Tkinter 组件库) 应用"),
        ("no-qt", "目标程序完全不依赖 Qt 时使用, 排除 Qt 相关处理"),
    )),
    ("压缩 / 兼容", (
        ("upx", "UPX 压缩可执行文件 (需先安装 UPX, 未安装时选项标红)"),
        ("anti-bloat", "剔除冗余依赖与警告噪音, 减小体积、加快编译"),
        ("dll-files", "按第三方包配置自动打入相关 dll; 可能增大产物体积, 谨慎使用"),
        ("delvewheel", "修复 delvewheel 打包的 wheel (含外部 dll)"),
        ("enum-compat", "enum34 兼容补丁 (仅旧依赖需要)"),
        ("dill-compat", "dill 序列化兼容支持"),
        ("pbr-compat", "pbr 打包兼容支持"),
    )),
    ("数据科学 / 机器学习", (
        ("numpy", "NumPy 数值计算库"),
        ("matplotlib", "Matplotlib 绘图库"),
        ("tensorflow", "TensorFlow 深度学习框架"),
        ("torch", "PyTorch 深度学习框架"),
        ("torch-hub", "PyTorch Hub 预训练模型下载"),
        ("torch-jit", "PyTorch JIT (TorchScript) 模型"),
        ("transformers", "Hugging Face Transformers 模型"),
        ("spacy", "spaCy 自然语言处理库"),
    )),
    ("并发 / 网络", (
        ("trio", "Trio 异步框架"),
        ("gevent", "gevent 协程库"),
        ("eventlet", "eventlet 协程库"),
        ("multiprocessing", "multiprocessing 多进程 (用到多进程时勾选)"),
        ("playwright", "Playwright 浏览器自动化"),
    )),
    ("内部 / 高级", (
        ("pylint-warnings", "遵循 pylint 注释控制隐式导入"),
        ("pkg-resources", "pkg_resources 入口点 (entry points) 支持"),
        ("options-nanny", "检查 Nuitka 选项组合是否合理"),
        ("implicit-imports", "允许插件声明隐式导入 (调试缺失模块用)"),
        ("source-inclusion", "将源码包含进产物, 便于回溯调试"),
        ("data-files", "自动包含已安装包内的数据文件"),
    )),
)

# 扁平插件名列表 (保持兼容: 配置读取/收藏等按名字索引)
PLUGIN_OPTIONS = [name for _, plugins in PLUGIN_GROUPS for name, _ in plugins]

MODE_OPTIONS = (
    ("onefile", "单文件打包"),
    ("onedir", "单目录打包"),
    ("module", "打包为模块"),
)
MODE_TO_LABEL = dict(MODE_OPTIONS)
MODE_FROM_LABEL = {label: value for value, label in MODE_OPTIONS}

LTO_OPTIONS = (
    ("auto", "自动 (默认)"),
    ("yes", "开启 LTO"),
    ("no", "关闭 LTO"),
)
LTO_TO_LABEL = dict(LTO_OPTIONS)
LTO_FROM_LABEL = {label: value for value, label in LTO_OPTIONS}

# Nuitka 输出中的阶段关键字 -> (显示文本, 进度百分比), 按进度从低到高排列。
# 关键字来源: MainControl.py 的 general.info() 调用, 已核对 Nuitka 4.2.x 实际输出。
# C 编译阶段由 Scons 接管, 子进程模式下无模块级进度, 仅能识别"开始/链接"两端点。
PROGRESS_STEPS = (
    ("starting python compilation", "启动 Nuitka", 2),
    ("downloading", "下载编译器/依赖", 5),
    ("completed python level compilation", "Python 编译完成", 35),
    ("generating source code", "生成 C 源码", 50),
    ("running data composer", "生成数据", 60),
    ("running c compilation", "C 编译开始", 72),
    ("c linking", "C 编译完成/链接", 90),
    ("successfully created", "完成", 100),
)

# 打包失败诊断规则: (正则, 问题标题, 修复建议)。
# 按优先级排列, 命中即认为该原因(针对日志全文匹配)。
# 注意: 命令回显行也会出现在日志中, 规则必须匹配真正的报错文案,
# 不要用命令行参数名(如 --file-version)做关键词, 否则会误报。
# 规则中可用命名组 (?P<path>...) 提取实际路径, 通过 {path} 填入标题/建议。
_IS_WIN = os.name == "nt"  # 平台判断, 用于 FAILURE_RULES 里 Windows 专属提示

FAILURE_RULES = (
    (r"icon path ['\"](?P<path>[^'\"]+)['\"] does not exist",
     "图标文件路径不存在",
     ("请检查「Windows 信息」页签的图标设置: 当前路径 '{path}' 不存在, "
      "请重新选择有效的 .ico 文件") if _IS_WIN
     else ("图标路径 '{path}' 不存在, 请重新选择有效图标文件(.png/.ico/.svg 等)")),
    (r"(?:sconslockfailure: )?timeout waiting for lock on ['\"](?P<path>[^'\"]+)['\"]"
     r"|sconslockfailure",
     "Scons 编译锁超时 (缓存被占用)",
     "通常是有另一个 Nuitka 打包进程在运行, 或杀毒软件锁定了 Nuitka 缓存。"
     + (("建议: ① 关闭其它打包窗口后重试; ② 仍失败则删除缓存目录 %%LOCALAPPDATA%%\\Nuitka 后重试; "
        "③ 杀毒软件拦截请把 Nuitka 缓存目录加入白名单。") if _IS_WIN
        else ("建议: ① 关闭其它打包窗口后重试; ② 仍失败则删除 ~/.cache/Nuitka 后重试。"))
     + " (锁文件: {path})"),
    (r"cannot use '--mingw64' on python|mingw64.{0,40}not supported|"
     r"no suitable c compiler|did not find.{0,40}(c compiler|compiler)",
     "缺少可用的 C 编译器",
     (("Python 3.13+ 必须使用 MSVC: winget install Microsoft.VisualStudio.2022.BuildTools") if _IS_WIN
      else ("请安装 gcc/clang: sudo apt install build-essential (Debian/Ubuntu) / "
            "sudo dnf install gcc gcc-c++ (Fedora) / brew install gcc (macOS)"))),
    (r"unknown plug-?in",
     "插件名不正确",
     "检查插件名拼写与大小写(如 pyside6/pyqt6 均为小写), 并确认已安装对应依赖"),
    (r"invalid version number",
     "Windows 版本号格式错误",
     "版本号只能包含数字和点(如 1.0.0), 不要带 V/v 前缀"),
    (r"no module named|modulenotfounderror|importerror",
     "目标脚本缺少 Python 依赖",
     "先安装日志中提到的模块: pip install <模块名>"),
    (r"cannot add data (file|dir)|include-data-.*not exist|source.*does not exist",
     "数据文件/目录路径错误",
     "检查「数据与模块」中填写的本地路径是否存在"),
    (r"no space left on device|磁盘空间不足|insufficient disk space",
     "磁盘空间不足",
     "清理磁盘空间, 或把输出目录改到空间充足的磁盘"),
    (r"permission denied|access is denied|拒绝访问",
     "没有写入权限",
     "以管理员身份运行程序, 或把输出目录改到可写位置"),
    (r"fatal error c\d{4}|error c\d{3,4}|\.c\(.+\)\s*:\s*error",
     "C 编译器报错 (目标代码或第三方扩展)",
     "查看日志中具体 C 错误行; 多为第三方库需更新、或缺少 C 头文件"),
    (r"failed unexpectedly in scons|scons.*backend",
     "C 编译阶段异常退出 (Scons)",
     "多为编译器或缓存问题: 清理 Nuitka 缓存后重试, 必要时重装 MSVC Build Tools"),
    (r"unknown option|no such option|not recognized option|option[^\n]{0,25}unknown",
     "参数不被当前 Nuitka 支持",
     "升级 Nuitka: pip install -U nuitka"),
    (r"failed to download|download.{0,20}failed|timed out|无法连接|网络错误",
     "网络/下载失败",
     "检查网络后重试; 使用代理时请先配置系统代理"),
    (r"system cannot find|系统找不到指定的文件|winerror 2",
     "找不到命令或文件",
     "脚本/输出路径不存在; 打包需要本机已安装 Python 且包含 Nuitka"),
    (r"syntaxerror|indentationerror",
     "目标脚本存在语法错误",
     "先在 IDE 中运行目标脚本, 确认无语法错误再打包"),
    (r"failed to create|cannot create output|could not create",
     "无法创建输出目录/文件",
     "检查输出目录路径是否合法、权限是否足够"),
)

# 没有命中任何具体规则时的兜底提示
_FALLBACK_HINT = ("未能识别具体原因",
                  "请查看日志中 FATAL 行后面的具体错误描述, 或把日志发给我们排查")


def analyze_failure(log_text):
    """从构建日志中识别常见失败原因。

    返回 [(问题标题, 修复建议), ...], 去重保序; 没有命中时返回空列表。
    规则若定义了命名组 path, 会把实际路径动态填入标题/建议中的 {path}。
    """
    low = (log_text or "").lower()
    found = []
    for pattern, title, fix in FAILURE_RULES:
        try:
            m = re.search(pattern, low)
        except re.error:
            continue
        if not m:
            continue
        try:
            path = m.group("path")
        except IndexError:
            path = None
        if path:
            title = title.replace("{path}", path)
            fix = fix.replace("{path}", path)
        else:
            # 未捕获到具体路径时, 去掉建议中依赖路径的片段
            fix = fix.replace(" (锁文件: {path})", "").replace("{path}", "")
        found.append((title, fix))
    # 未命中任何具体规则时, 才显示兜底提示, 避免和具体诊断混在一起
    if not found:
        found.append(_FALLBACK_HINT)
    seen = set()
    uniq = []
    for title, fix in found:
        if title not in seen:
            seen.add(title)
            uniq.append((title, fix))
    return uniq

# 日志区样式与文字颜色(按主题)
LOG_STYLES = {
    "light": ("QPlainTextEdit{background:#f7f9fc;color:#1f2328;"
              "font-family:Consolas;font-size:9.5pt;padding:6px;"
              "border:1px solid #b8c6d9;border-radius:6px;"
              "selection-background-color:#cfe4fb;}"),
    "dark": ("QPlainTextEdit{background:#111214;color:#d4d4d4;"
             "font-family:Consolas;font-size:9pt;border:1px solid #3f4248;"
             "border-radius:6px;}"),
}
LOG_COLOR_SETS = {
    "light": {"cmd": "#0f5cad", "ok": "#1e7d33", "warn": "#a06a00",
              "error": "#d11f1f", "normal": "#1f2328"},
    "dark": {"cmd": "#5aa7e0", "ok": "#6fd18a", "warn": "#e5c07b",
             "error": "#f26d6d", "normal": "#d4d4d4"},
}

# 选项卡定义: (页签标题, 构建方法名)。除首个外均懒加载(切换时构建)
TAB_SPECS = (
    ("基本选项", "_build_basic_tab"),
    ("插件", "_build_plugin_tab"),
    ("数据与模块", "_build_data_tab"),
    ("Windows 信息", "_build_win_tab"),
    ("高级", "_build_advanced_tab"),
)



# 行级别智能分级: stdout 行若含错误/警告关键词, 自动提升日志级别
# 这些关键词必须在 stderr 缺失时能精准定位问题 (Nuitka 多数 FATAL 也会走 stderr,
# 但历史上 PyQt5 插件检测 FATAL 就曾打到 stdout)
_LOG_LEVEL_HINTS = [
    # (小写子串, 要提升的 level)
    ("fatal", "error"),
    ("traceback", "error"),
    ("exception", "error"),
    ("error:", "error"),
    ("error c", "error"),    # MSVC C 编译器错误
    ("  error ", "error"),   # Nuitka 模块内的 ERROR 标记
    ("warning:", "warn"),
    ("  warning ", "warn"),
]


def _classify_line_level(line):
    """根据内容判断 stdout 行的建议日志级别。

    默认 normal; 匹配到 FATAL/ERROR 关键词 → error, 匹配到 WARNING → warn。
    """
    low = (line or "").lower()
    for hint, level in _LOG_LEVEL_HINTS:
        if hint in low:
            return level
    return "normal"


class WorkerQueue:
    """把 builder/deps 的 log_queue.put(item) 转发为 Qt 信号(跨线程安全)。"""

    def __init__(self, worker):
        self._worker = worker

    def put(self, item):
        kind, payload = item
        if kind == "cmd":
            self._worker.command.emit(payload)
        elif kind == "line":
            self._worker.output.emit(payload)
        elif kind == "error":
            self._worker.error.emit(payload)
        elif kind == "ok":
            self._worker.ok.emit(payload)
        elif kind in ("done", "mingw_done"):
            self._worker.done.emit(payload)


class BuildWorker(QObject):
    """在后台线程执行打包/下载任务, 通过信号回传主线程。"""

    command = Signal(str)
    output = Signal(str)
    error = Signal(str)
    ok = Signal(str)
    done = Signal(int)

    def start(self, target, queue, stop_event, *args):
        def _run():
            try:
                target(queue, stop_event, *args)
            except Exception as exc:  # 防止后台线程异常导致静默失败
                self.error.emit(str(exc))
                self.done.emit(-1)

        threading.Thread(target=_run, daemon=True).start()


class EnvWorker(QObject):
    """在后台线程执行环境检查。"""

    finished = Signal(list)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        self.finished.emit(deps.run_env_check())


class ThreeBodyIndicator(QWidget):
    """不确定进度指示器

    三个圆点构成三角形, 整体匀速自转; 每个圆点沿径向摆动并伴随
    缩放与透明度变化, 视觉上"三点追赶旋转", 表示任务进行中。
    """

    def __init__(self, parent=None, size=36, speed=0.8, color="#C19A6B", alpha=0.7):
        super().__init__(parent)
        self._size = size
        self._speed = speed
        self._color = QColor(color)
        self._alpha = alpha
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self.update)
        self._running = False

    def setRunning(self, running):
        self._running = bool(running)
        if self._running:
            self._elapsed.restart()
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def isRunning(self):
        return self._running

    def paintEvent(self, _event):
        if not self._running:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        t = self._elapsed.elapsed() / 1000.0
        center = QPointF(self._size / 2.0, self._size / 2.0)
        radius = self._size * 0.19          # 三角形外接圆半径(收缩防溢出)
        dot_d = self._size * 0.28           # 圆点直径
        spin = (t / (self._speed * 2.5)) * 360.0   # 整体自转
        base_angles = (90.0, 210.0, 330.0)  # 顶 / 左下 / 右下
        phases = (-0.3, -0.15, 0.0)         # 摆动相位(错开)
        two_pi = 2.0 * math.pi
        for idx, (ang, ph) in enumerate(zip(base_angles, phases)):
            m = math.sin(two_pi * (t / self._speed) + two_pi * ph)
            if idx == 2:                    # 第三个圆点反向摆动
                m = -m
            scale = 1.0 - 0.35 * abs(m)     # 0.65 ~ 1.0
            alpha = 1.0 - 0.20 * abs(m)     # 0.8 ~ 1.0
            rad = radius * (1.0 + 0.66 * m)  # 径向摆动 ±66%
            a = math.radians(spin + ang)
            x = center.x() + rad * math.cos(a)
            y = center.y() - rad * math.sin(a)
            color = QColor(self._color)
            color.setAlphaF(self._alpha * alpha)  # 全局 0.7 透明度 × 摆动透明度
            p.setBrush(color)
            p.drawEllipse(QPointF(x, y), dot_d * scale / 2.0, dot_d * scale / 2.0)
        p.end()


class ArrowButton(QToolButton):
    """无文字的箭头按钮: 展开时朝下(▼), 折叠时朝右(▶)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setToolTip("展开 / 折叠")

    def setExpanded(self, expanded):
        self._expanded = bool(expanded)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#8a95a5"))
        if self._expanded:
            pts = [QPointF(4, 6), QPointF(14, 6), QPointF(9, 12)]
        else:
            pts = [QPointF(6, 4), QPointF(6, 14), QPointF(12, 9)]
        p.drawPolygon(QPolygonF(pts))
        p.end()


class CollapsibleBox(QWidget):
    """可折叠分组: 标题行(箭头按钮 + 标题) + 内容区, 点击箭头切换展开/折叠。"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(8, 5, 8, 5)
        hl.setSpacing(6)
        self._btn = ArrowButton()
        self._btn.clicked.connect(self._toggle)
        hl.addWidget(self._btn)
        title_lbl = QLabel(title)
        font = title_lbl.font()
        font.setBold(True)
        title_lbl.setFont(font)
        hl.addWidget(title_lbl)
        hl.addStretch()
        self._layout.addWidget(header)

        self._content = QWidget()
        self._layout.addWidget(self._content)

    def content(self):
        """返回内容容器, 外部把内容放进去。"""
        return self._content

    def isExpanded(self):
        return self._content.isVisible()

    def _toggle(self):
        expanded = not self.isExpanded()
        self._content.setVisible(expanded)
        self._btn.setExpanded(expanded)

    def set_theme(self, qss):
        self.setStyleSheet(qss)


def collapsible_qss(theme):
    """可折叠分组的卡片样式(按主题)。"""
    if theme == "dark":
        return (".CollapsibleBox{background:#2b2d31;"
                "border:1px solid #3f4248;border-radius:8px;}")
    return (".CollapsibleBox{background:#ffffff;"
            "border:1px solid #e3e8ef;border-radius:8px;}")


def _sanitize_dest(dest):
    """清洗并校验"程序内"目标路径; 非法返回 None, 空返回 ""。

    Nuitka 的 --include-data-dir/files 目标必须是相对可执行文件的相对路径,
    以下情况会导致打包失败或产物结构错乱, 一律拒绝:
    - 盘符 (C:...) 或前导 / \\ (绝对路径)
    - ".." (路径逃逸出产物根目录)
    - 通配符与 shell/文件名敏感字符 (* ? " ' < > |)
    反斜杠统一为正斜杠, 折叠 "." 与重复斜杠。
    """
    dest = (dest or "").strip().replace("\\", "/")
    if not dest:
        return ""
    if re.match(r"^[A-Za-z]:", dest) or dest.startswith("/"):
        return None
    parts = []
    for part in dest.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    if not parts:
        return ""
    cleaned = "/".join(parts)
    if any(ch in cleaned for ch in "*?\"'<>|"):
        return None
    return cleaned


class RowTableEditor(QGroupBox):
    """数据资源编辑器: 两列"本地 → 程序内"表格, 表头自解释, 无需说明文字。

    列表以表格呈现(表头: 本地路径 | 程序内路径), 每个字段对应打包后的
    存放位置, 比"来源=目标"自由文本直观得多。
    """

    def __init__(self, title, parent=None, picker="dir", root_resolver=None):
        super().__init__(title, parent)
        self._picker = picker  # "dir" 浏览选目录 / "file" 浏览选文件
        # 返回项目源码根目录(主脚本所在目录)的回调; 用于计算资源相对路径
        self._root_resolver = root_resolver
        self._items = []  # [(src, dest), ...]
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        entry_row.addWidget(QLabel("本地"))
        self.ed_src = QLineEdit()
        entry_row.addWidget(self.ed_src, 1)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse)
        self._browse_btn = browse_btn
        entry_row.addWidget(browse_btn)
        entry_row.addWidget(QLabel("→"))
        entry_row.addWidget(QLabel("程序内"))
        self.ed_dest = QLineEdit()
        self.ed_dest.setPlaceholderText("可留空")
        entry_row.addWidget(self.ed_dest, 1)
        add_btn = QPushButton("+ 添加")
        add_btn.clicked.connect(self._add)
        self._add_btn = add_btn
        entry_row.addWidget(add_btn)
        layout.addLayout(entry_row)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["本地路径", "程序内路径"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(96)
        layout.addWidget(self.table)

        rm_btn = QPushButton("删除选中")
        rm_btn.clicked.connect(self._remove)
        layout.addWidget(rm_btn)

    def _project_root(self):
        """项目源码根目录: 主脚本所在目录; 未选脚本时返回 None。"""
        if not callable(self._root_resolver):
            return None
        try:
            root = self._root_resolver()
        except Exception:
            return None
        if root:
            root = os.path.abspath(root)
            if os.path.isdir(root):
                return root
        return None

    def _compute_dest(self, path):
        """由所选路径推算"程序内"目标路径 (相对项目根目录)。

        已选主脚本 → 计算相对主脚本所在目录的路径, 使产物内结构与源码
        目录一致, 运行时以相对路径引用最稳妥。
        异常处理:
        - Windows 跨盘符无法计算 → 提示并退化为文件名;
        - 资源在项目根之外 (relpath 含 ..) → 剥离前导 .. 段并提示;
        - 未选主脚本 / 资源就是项目根本身 → 退化为文件名。
        """
        root = self._project_root()
        if not root:
            return os.path.basename(path.rstrip("/\\"))
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            # Windows 跨盘符 (如 D: 与 E:), relpath 无法计算
            self._warn("所选资源与主脚本不在同一磁盘, 无法计算相对"
                       "路径, 已使用文件名作为程序内路径")
            return os.path.basename(path.rstrip("/\\"))
        parts = rel.replace("\\", "/").split("/")
        outside = False
        while parts and parts[0] == "..":
            parts.pop(0)
            outside = True
        # 去掉 "." 段 (如资源就是项目根本身时 relpath = ".")
        parts = [p for p in parts if p != "."]
        if not parts:
            return os.path.basename(path.rstrip("/\\"))
        dest = "/".join(parts)
        if outside:
            self._warn("所选资源在项目源码根目录之外, 程序内路径"
                       "已截断为 %r" % dest)
        return dest

    def _browse(self):
        """浏览选择本地文件/目录; 选中后自动推算目标路径并直接加入列表。

        浏览即生效: 省去"填完还要点添加"的步骤, 资源立即进入打包命令
        (预览命令中可见)。用户已填目标路径时尊重原值; 若被校验/冲突
        检测拒绝, 输入保留并气泡说明原因, 改完点「+ 添加」即可。
        """
        if self._picker == "file":
            path, _ = QFileDialog.getOpenFileName(
                self, "选择文件", "", "所有文件 (*.*)")
        else:
            path = QFileDialog.getExistingDirectory(self, "选择目录")
        if not path:
            return
        self.ed_src.setText(path)
        if not self.ed_dest.text().strip():
            dest = self._compute_dest(path)
            if dest:
                self.ed_dest.setText(dest)
        self._add()

    def set_input_enabled(self, enabled):
        """启用/禁用填写控件(浏览/来源/目标/添加); 表格与删除不受影响。"""
        for w in (self._browse_btn, self.ed_src, self.ed_dest, self._add_btn):
            w.setEnabled(enabled)

    def _warn(self, msg):
        """在「+ 添加」按钮处弹出气泡提示, 不打断操作、不清空已填内容。"""
        QToolTip.showText(
            self._add_btn.mapToGlobal(QPoint(0, self._add_btn.height())),
            msg, self._add_btn)

    def _add(self):
        src = self.ed_src.text().strip()
        if not src:
            return
        dest = _sanitize_dest(self.ed_dest.text())
        if dest is None:
            self._warn("程序内路径必须是相对路径: 不能以盘符或 / 开头, "
                       "不能含 .. 与 * ? \" ' < > | 等字符")
            return
        # 目标冲突检测: 空 dest 时 Nuitka 按源 basename 放置, 同 basename
        # 的多个条目会互相覆盖 (Duplication), 按同一把尺子查重
        effective = dest or os.path.basename(src.rstrip("/\\"))
        for exist_src, exist_dest in self._items:
            exist_effective = exist_dest or os.path.basename(
                exist_src.rstrip("/\\"))
            if effective and effective == exist_effective:
                self._warn("目标路径 %r 已被占用, 请修改「程序内」列区分"
                           % effective)
                return
        self._items.append((src, dest))
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(src))
        self.table.setItem(row, 1, QTableWidgetItem(dest))
        self.ed_src.clear()
        self.ed_dest.clear()

    def _remove(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        del self._items[row]

    def set_items(self, items):
        """items: ["src=dest", "src", ...] 或 [(src, dest), ...]"""
        self.table.setRowCount(0)
        self._items = []
        for it in items:
            if isinstance(it, tuple):
                src, dest = it
            elif "=" in it:
                src, dest = it.split("=", 1)
            else:
                src, dest = it, ""
            self._items.append((src, dest))
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(src))
            self.table.setItem(row, 1, QTableWidgetItem(dest))

    def get_items(self):
        return ["%s=%s" % (s, d) if d else s for s, d in self._items]


class ModuleListEditor(QGroupBox):
    """模块与导入控制: 单选切换类型, 各自独立列表, 按钮文本显示数量。"""

    TYPES = (("include_packages", "包含包"),
             ("include_modules", "包含模块"),
             ("exclude_modules", "排除导入"))

    def __init__(self, parent=None):
        super().__init__("模块与导入", parent)
        self._data = {key: [] for key, _ in self.TYPES}
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        radio_row = QHBoxLayout()
        radio_row.setSpacing(14)
        self.radio = {}
        grp = QButtonGroup(self)
        type_tips = {
            "include_packages": "包含包: 将整个 Python 包(含其数据文件)打入产物",
            "include_modules": "包含模块: 将单个 .py 模块打入产物",
            "exclude_modules": "排除导入: 打包时排除不需要的模块, 减小产物体积",
        }
        for key, _label in self.TYPES:
            rb = QRadioButton("")
            rb.setToolTip(type_tips[key])
            self.radio[key] = rb
            grp.addButton(rb)
            rb.toggled.connect(self._refresh_list)
            radio_row.addWidget(rb)
        radio_row.addStretch()
        self.radio["include_packages"].setChecked(True)
        layout.addLayout(radio_row)

        entry_row = QHBoxLayout()
        entry_row.setSpacing(6)
        self.ed_name = QLineEdit()
        entry_row.addWidget(self.ed_name, 1)
        add_btn = QPushButton("+ 添加")
        add_btn.clicked.connect(self._add)
        entry_row.addWidget(add_btn)
        layout.addLayout(entry_row)

        self._list = QListWidget()
        self._list.setMinimumHeight(80)
        layout.addWidget(self._list)

        rm_btn = QPushButton("删除选中")
        rm_btn.clicked.connect(self._remove)
        layout.addWidget(rm_btn)

    def _current(self):
        for key, rb in self.radio.items():
            if rb.isChecked():
                return key
        return "include_packages"

    def _add(self):
        name = self.ed_name.text().strip()
        if not name:
            return
        key = self._current()
        self._data[key].append(name)
        self._refresh_list()
        self.ed_name.clear()

    def _remove(self):
        row = self._list.currentRow()
        if row < 0:
            return
        key = self._current()
        if 0 <= row < len(self._data[key]):
            del self._data[key][row]
            self._refresh_list()

    def _refresh_list(self):
        key = self._current()
        if getattr(self, "_list", None) is not None:
            self._list.clear()
            for item in self._data[key]:
                self._list.addItem(item)
        labels = dict(self.TYPES)
        for k, rb in self.radio.items():
            rb.setText("%s (%d)" % (labels[k], len(self._data[k])))

    def set_data(self, data):
        self._data = {key: list(data.get(key, [])) for key, _ in self.TYPES}
        self._refresh_list()

    def get_data(self):
        return {key: list(items) for key, items in self._data.items()}


class NuitkaGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nuitka 打包工具")
        self.setMinimumSize(900, 640)
        self.resize(900, 640)

        self.stop_event = threading.Event()
        self.building = False
        self._worker = None
        self._env_worker = None
        self._current_task = None
        self.env_nuitka_ok = False
        self.env_compiler_ok = False
        self.theme = "light"
        self.log_colors = LOG_COLOR_SETS["light"]
        self._built_tabs = set()
        self._pending_cfg = None

        cfg = load_config()
        self.theme = cfg.get("theme", "light")
        # 提速关键: 在创建任何子控件之前先在应用级应用完整样式, 让每个控件在
        # 创建时就完成样式解析; 若窗口构建完成后再从"无样式"一次性应用完整 QSS,
        # Qt 会对整棵控件树重新抛光(实测 ~1.3s)。运行时主题切换仍走窗口级, 仅 ~0.01s。
        QApplication.instance().setStyleSheet(
            APP_QSS if self.theme == "light" else APP_DARK_QSS)

        self._build_ui()
        self._build_menu()
        self._load_from_config(cfg)
        self._apply_theme_parts()  # 窗口级样式未设置, 只补局部部件样式
        # 启动后自动做一次环境检查(后台线程, 不阻塞界面)
        QTimer.singleShot(100, self._start_env_check)

    # ---------- 界面 ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(10)
        root.setContentsMargins(12, 8, 12, 12)

        # 顶部: 项目基本信息(紧凑网格)
        top = QGroupBox("项目")
        grid = QGridLayout(top)
        grid.setContentsMargins(14, 16, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.ed_script = QLineEdit()
        self.ed_output_dir = QLineEdit()
        self.ed_output_name = QLineEdit()
        self.cb_mode = QComboBox()
        self.cb_mode.addItems([label for _, label in MODE_OPTIONS])
        self.rb_console_yes = QRadioButton("保留控制台")
        self.rb_console_no = QRadioButton("隐藏控制台")
        self.rb_console_yes.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_console_yes)
        grp.addButton(self.rb_console_no)
        console_row = QHBoxLayout()
        console_row.setSpacing(14)
        console_row.addWidget(self.rb_console_yes)
        console_row.addWidget(self.rb_console_no)
        console_row.addStretch()

        def label(text):
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return lbl

        grid.addWidget(label("主脚本:"), 0, 0)
        grid.addWidget(self.ed_script, 0, 1)
        grid.addWidget(self._browse_btn(self._pick_script), 0, 2)
        grid.addWidget(label("输出目录:"), 1, 0)
        grid.addWidget(self.ed_output_dir, 1, 1)
        grid.addWidget(self._browse_btn(self._pick_output_dir), 1, 2)
        grid.addWidget(label("输出文件名:"), 2, 0)
        grid.addWidget(self.ed_output_name, 2, 1)
        grid.addWidget(label("打包模式:"), 2, 2)
        grid.addWidget(self.cb_mode, 2, 3)
        # 模式切换实时同步数据页签: 仅单文件模式允许填写(页签未构建时安全跳过)
        self.cb_mode.currentIndexChanged.connect(self._sync_data_tab_mode)
        grid.addWidget(label("控制台:"), 3, 0)
        grid.addLayout(console_row, 3, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(top)

        # 选项卡(懒加载: 仅首屏构建"基本选项", 其余切换时构建)
        self.tabs = QTabWidget()
        for label, _fn in TAB_SPECS:
            self.tabs.addTab(QWidget(), label)
        self.tabs.currentChanged.connect(self._ensure_tab)
        self._ensure_tab(0)
        root.addWidget(self.tabs, 2)

        # 日志区(可折叠, 保留标题与无文字箭头按钮)
        self.log_box = CollapsibleBox("构建日志")
        log_layout = QVBoxLayout(self.log_box.content())
        log_layout.setContentsMargins(10, 8, 10, 10)
        log_layout.setSpacing(6)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(100)
        log_layout.addWidget(self.log_text, 1)

        log_btns = QHBoxLayout()
        log_btns.setSpacing(8)
        self.btn_env = QPushButton("环境检查")
        self.btn_mingw = QPushButton("下载 MinGW64")
        btn_preview = QPushButton("预览命令")
        btn_clear = QPushButton("清空日志")
        self.btn_env.clicked.connect(self._start_env_check)
        self.btn_mingw.clicked.connect(self._download_mingw)
        self.btn_mingw.setEnabled(False)
        btn_preview.clicked.connect(self._preview_command)
        btn_clear.clicked.connect(self._clear_log)
        for b in (self.btn_env, self.btn_mingw, btn_preview, btn_clear):
            log_btns.addWidget(b)
        log_btns.addStretch()
        log_layout.addLayout(log_btns)
        root.addWidget(self.log_box, 1)

        # 底部操作栏
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.progress = ThreeBodyIndicator()
        self.lbl_status = QLabel("就绪")
        self.btn_start = QPushButton("开始打包")
        self.btn_start.setObjectName("primaryBtn")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        self.btn_start.clicked.connect(self._start_build)
        self.btn_cancel.clicked.connect(self._cancel_build)
        bottom.addWidget(self.progress)
        bottom.addWidget(self.lbl_status, 1)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_cancel)
        root.addLayout(bottom)

    def _browse_btn(self, slot):
        btn = QPushButton("浏览...")
        btn.clicked.connect(slot)
        return btn

    def _scrollable(self):
        """返回 (QScrollArea, 内容控件); 内容超高时自动出现滚动条"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        return scroll, content

    # ---------- 选项卡懒加载 ----------
    def _ensure_tab(self, idx):
        """首次切换到某页签时才构建其内容, 降低启动开销。"""
        if idx in self._built_tabs:
            return
        self._built_tabs.add(idx)
        label, fn_name = TAB_SPECS[idx]
        widget = getattr(self, fn_name)()
        self.tabs.removeTab(idx)
        self.tabs.insertTab(idx, widget, label)
        self.tabs.setCurrentIndex(idx)
        if self._pending_cfg is not None:
            self._apply_tab_cfg(idx, self._pending_cfg)

    def _ensure_all_tabs(self):
        """确保全部页签已构建(读取/保存完整配置前调用)。"""
        for i in range(len(TAB_SPECS)):
            self._ensure_tab(i)

    def _apply_tab_cfg(self, idx, cfg):
        """把配置恢复到指定页签的控件(懒加载页签首次构建后调用)。"""
        if idx == 0:  # 基本选项
            self.cb_lto.setCurrentText(LTO_TO_LABEL.get(cfg.get("lto", "auto"),
                                                        LTO_TO_LABEL["auto"]))
            self.spin_jobs.setValue(int(cfg.get("jobs") or 4))
            self.chk_remove.setChecked(bool(cfg.get("remove_output", False)))
        elif idx == 1:  # 插件
            saved = {p.lower() for p in cfg.get("plugins", [])}
            for name, cb in self.plugin_checks.items():
                cb.setChecked(name in saved)
        elif idx == 2:  # 数据与模块
            self.ed_data_dirs.set_items(cfg.get("data_dirs", []))
            self.ed_data_files.set_items(cfg.get("data_files", []))
            self.ed_modules.set_data({
                "include_packages": cfg.get("include_packages", []),
                "include_modules": cfg.get("include_modules", []),
                "exclude_modules": cfg.get("exclude_modules", []),
            })
        elif idx == 3:  # Windows 信息
            self.ed_company.setText(cfg.get("company_name", ""))
            self.ed_product.setText(cfg.get("product_name", ""))
            self.ed_file_version.setText(cfg.get("file_version", ""))
            self.ed_product_version.setText(cfg.get("product_version", ""))
            self.ed_description.setText(cfg.get("file_description", ""))
            self.ed_copyright.setText(cfg.get("copyright", ""))
        elif idx == 4:  # 高级
            self.ed_extra.setText(cfg.get("extra_args", ""))

    def _build_plugin_tab(self):
        scroll, content = self._scrollable()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        # 运行时自动发现 Nuitka 实际安装的插件 (deps 静态解析, 不执行插件代码)
        available = deps.list_nuitka_plugins()
        ok_nuitka, nuitka_ver = deps.check_nuitka()
        info = QLabel()
        info.setProperty("hint", True)
        info.setWordWrap(True)
        if available:
            info.setText("已自动发现 %d 个插件 (Nuitka %s)。Nuitka 升级新增的插件"
                         "会自动出现在「其他」组, 已移除的插件不再显示。"
                         % (len(available), nuitka_ver if ok_nuitka else "未知版本"))
        else:
            info.setText("未能自动发现插件 (未检测到 Nuitka 安装), 暂时显示内置列表;"
                         " 安装 Nuitka 后重启本工具即切换为自动发现。")
        layout.addWidget(info)

        # 分组视图: 已知插件沿用内置分组与说明, 仅保留实际安装存在的;
        # 内置列表之外的新发现插件归入「其他」; 发现失败则回退内置全量
        known = {name for _, plugins in PLUGIN_GROUPS for name, _ in plugins}
        if available:
            groups = [(title, [(n, t) for n, t in plugins if n in available])
                      for title, plugins in PLUGIN_GROUPS]
            extra = sorted(available - known)
            if extra:
                groups.append(("其他 (自动发现)",
                               [(n, "Nuitka 新增插件, 暂无说明") for n in extra]))
        else:
            groups = list(PLUGIN_GROUPS)

        self.plugin_checks = {}
        cols = 5
        for group_title, plugins in groups:
            if not plugins:
                continue
            group = QGroupBox(group_title)
            grid = QGridLayout(group)
            grid.setContentsMargins(12, 14, 12, 12)
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(6)
            for cell, (name, tip) in enumerate(plugins):
                cb = QCheckBox(name)
                if tip:
                    cb.setToolTip(tip)
                self.plugin_checks[name] = cb
                grid.addWidget(cb, cell // cols, cell % cols)
            layout.addWidget(group)

        # UPX 勾选后检查是否存在, 缺失时以淡红提示
        upx_cb = self.plugin_checks.get("upx")
        if upx_cb is not None:
            upx_cb.toggled.connect(self._update_upx_marker)
        layout.addStretch()
        return scroll

    def _update_upx_marker(self):
        """UPX 被勾选但系统未安装时, 将选项标记为淡红色(柔和, 不刺眼)。"""
        cb = self.plugin_checks.get("upx") if hasattr(self, "plugin_checks") else None
        if cb is None:
            return
        if cb.isChecked() and not deps.check_upx():
            cb.setStyleSheet("QCheckBox{color:#d98a8a;}")
        else:
            cb.setStyleSheet("")

    def _build_basic_tab(self):
        scroll, content = self._scrollable()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        # 图标 (Windows 支持 .ico 嵌入 PE, 跨平台仅打包进产物供运行时使用)
        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        icon_label = "图标 (.ico):" if os.name == "nt" else "图标 (可选, 任意格式):"
        icon_row.addWidget(QLabel(icon_label))
        self.ed_icon = QLineEdit()
        icon_row.addWidget(self.ed_icon, 1)
        btn_icon = QPushButton("浏览...")
        btn_icon.clicked.connect(self._pick_icon)
        icon_row.addWidget(btn_icon)
        layout.addLayout(icon_row)

        # 优化选项
        opt_group = QGroupBox("优化与构建选项")
        opt_form = QGridLayout(opt_group)
        opt_form.setContentsMargins(12, 16, 12, 12)
        opt_form.setHorizontalSpacing(10)
        opt_form.setVerticalSpacing(8)
        opt_form.addWidget(QLabel("LTO:"), 0, 0)
        self.cb_lto = QComboBox()
        self.cb_lto.addItems([label for _, label in LTO_OPTIONS])
        opt_form.addWidget(self.cb_lto, 0, 1)
        opt_form.addWidget(QLabel("并行任务数:"), 0, 2)
        self.spin_jobs = QSpinBox()
        self.spin_jobs.setRange(1, 32)
        self.spin_jobs.setValue(4)
        opt_form.addWidget(self.spin_jobs, 0, 3)
        self.chk_remove = QCheckBox("清理旧构建缓存")
        opt_form.addWidget(self.chk_remove, 1, 0, 1, 2)
        hint = QLabel("自动确认依赖下载已启用 (--assume-yes-for-downloads)")
        hint.setProperty("hint", True)
        opt_form.addWidget(hint, 1, 2, 1, 2)
        layout.addWidget(opt_group)
        layout.addStretch()
        return scroll

    def _build_data_tab(self):
        scroll, content = self._scrollable()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        # 数据资源仅单文件模式有效; 其他模式下停用填写并在此说明原因
        self.data_mode_hint = QLabel()
        self.data_mode_hint.setProperty("hint", True)
        self.data_mode_hint.setWordWrap(True)
        layout.addWidget(self.data_mode_hint)

        def root_resolver():
            return os.path.dirname(self.ed_script.text().strip()) or None
        self.ed_data_dirs = RowTableEditor(
            "数据目录", picker="dir", root_resolver=root_resolver)
        self.ed_data_files = RowTableEditor(
            "数据文件", picker="file", root_resolver=root_resolver)
        self.ed_modules = ModuleListEditor()

        layout.addWidget(self.ed_data_dirs)
        layout.addWidget(self.ed_data_files)
        layout.addWidget(self.ed_modules)
        layout.addStretch()
        self._sync_data_tab_mode()
        return scroll

    def _sync_data_tab_mode(self):
        """按打包模式同步数据资源填写区: 仅单文件模式允许填写。

        非单文件模式下停用浏览/来源/目标/添加控件并显示提示;
        已添加的条目保留不丢失, 切回单文件模式即恢复填写。
        """
        if not hasattr(self, "ed_data_dirs"):
            return  # 数据页签尚未构建
        mode = MODE_FROM_LABEL.get(self.cb_mode.currentText(), "onefile")
        is_onefile = mode == "onefile"
        self.ed_data_dirs.set_input_enabled(is_onefile)
        self.ed_data_files.set_input_enabled(is_onefile)
        if hasattr(self, "data_mode_hint"):
            if is_onefile:
                self.data_mode_hint.setVisible(False)
            else:
                self.data_mode_hint.setText(
                    "数据目录/文件仅在单文件打包 (--onefile) 模式下有效。"
                    "当前模式「%s」已停用填写, 切换到单文件模式后恢复; "
                    "已添加的条目会保留, 不会丢失。"
                    % self.cb_mode.currentText())
                self.data_mode_hint.setVisible(True)

    def _build_win_tab(self):
        scroll, content = self._scrollable()
        form = QFormLayout(content)
        form.setContentsMargins(16, 16, 16, 16)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.ed_company = QLineEdit()
        self.ed_product = QLineEdit()
        self.ed_file_version = QLineEdit()
        self.ed_product_version = QLineEdit()
        self.ed_description = QLineEdit()
        self.ed_copyright = QLineEdit()
        # 版本号输入框: 只允许数字与点, 从源头限制非法格式
        ver_validator = QRegularExpressionValidator(
            QRegularExpression(r"[0-9.]{0,20}"), self)
        for ed in (self.ed_file_version, self.ed_product_version):
            ed.setValidator(ver_validator)
            ed.setPlaceholderText("如 1.0.0")
        form.addRow("公司名称:", self.ed_company)
        form.addRow("产品名称:", self.ed_product)
        form.addRow("文件版本:", self.ed_file_version)
        form.addRow("产品版本:", self.ed_product_version)
        form.addRow("文件描述:", self.ed_description)
        form.addRow("版权信息:", self.ed_copyright)
        hint = QLabel("提示: 这些信息会写入打包产物的 Windows 文件属性中。"
                      "版本号仅支持数字与点, 如 1.0.0。")
        hint.setProperty("hint", True)
        form.addRow(hint)
        return scroll

    def _build_advanced_tab(self):
        scroll, content = self._scrollable()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(QLabel("附加参数 (空格分隔, 需带 -- 前缀):"))
        self.ed_extra = QLineEdit()
        layout.addWidget(self.ed_extra)
        hint = QLabel("示例: --python-flag=no_site  --windows-uac-admin  --nofollow-import-to=tkinter")
        hint.setProperty("hint", True)
        layout.addWidget(hint)
        layout.addStretch()
        return scroll

    def _build_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("保存配置", self._save_config_now)
        file_menu.addAction("加载配置", self._load_config_now)
        file_menu.addSeparator()
        file_menu.addAction("退出", self.close)

        view_menu = menubar.addMenu("视图")
        self.theme_group = QActionGroup(self)
        self.act_light = QAction("亮色模式", self)
        self.act_dark = QAction("暗色模式", self)
        for act in (self.act_light, self.act_dark):
            act.setCheckable(True)
            self.theme_group.addAction(act)
        view_menu.addAction(self.act_light)
        view_menu.addAction(self.act_dark)
        self.act_light.triggered.connect(lambda: self._apply_theme("light"))
        self.act_dark.triggered.connect(lambda: self._apply_theme("dark"))

        help_menu = menubar.addMenu("帮助")
        help_menu.addAction("关于", self._show_about)

    # ---------- 文件选择 ----------
    def _pick_script(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择主脚本", "", "Python 脚本 (*.py);;所有文件 (*.*)")
        if path:
            self.ed_script.setText(path)

    def _pick_output_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if path:
            self.ed_output_dir.setText(path)

    def _pick_icon(self):
        if os.name == "nt":
            flt = "图标文件 (*.ico);;所有文件 (*.*)"
        else:
            flt = "图标文件 (*.ico *.png *.svg *.icns);;所有文件 (*.*)"
        path, _ = QFileDialog.getOpenFileName(self, "选择图标", "", flt)
        if path:
            self.ed_icon.setText(path)

    # ---------- 配置 <-> 界面 ----------
    def _collect_config(self):
        self._ensure_all_tabs()  # 读取完整配置前确保所有页签已构建
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({
            "script": self.ed_script.text().strip() or DEFAULT_SCRIPT,
            "output_dir": self.ed_output_dir.text().strip(),
            "output_filename": self.ed_output_name.text().strip(),
            "mode": MODE_FROM_LABEL.get(self.cb_mode.currentText(), "onefile"),
            "console": self.rb_console_yes.isChecked(),
            "icon": self.ed_icon.text().strip(),
            "plugins": [name for name, cb in self.plugin_checks.items() if cb.isChecked()],
            "lto": LTO_FROM_LABEL.get(self.cb_lto.currentText(), "auto"),
            "jobs": self.spin_jobs.value(),
            "remove_output": self.chk_remove.isChecked(),
            "data_dirs": self.ed_data_dirs.get_items(),
            "data_files": self.ed_data_files.get_items(),
            **self.ed_modules.get_data(),
            "company_name": self.ed_company.text().strip(),
            "product_name": self.ed_product.text().strip(),
            "file_version": self.ed_file_version.text().strip(),
            "product_version": self.ed_product_version.text().strip(),
            "file_description": self.ed_description.text().strip(),
            "copyright": self.ed_copyright.text().strip(),
            "extra_args": self.ed_extra.text().strip(),
            "theme": self.theme,
        })
        return cfg

    def _load_from_config(self, cfg):
        self._pending_cfg = cfg
        # 公共控件(非页签)
        self.ed_script.setText(cfg.get("script", ""))
        self.ed_output_dir.setText(cfg.get("output_dir", ""))
        self.ed_output_name.setText(cfg.get("output_filename", ""))
        self.cb_mode.setCurrentText(MODE_TO_LABEL.get(cfg.get("mode", "onefile"),
                                                      MODE_TO_LABEL["onefile"]))
        self.rb_console_yes.setChecked(bool(cfg.get("console", True)))
        self.rb_console_no.setChecked(not bool(cfg.get("console", True)))
        self.ed_icon.setText(cfg.get("icon", ""))
        self.theme = cfg.get("theme", "light")
        # 已构建页签的控件
        for i in range(len(TAB_SPECS)):
            if i in self._built_tabs:
                self._apply_tab_cfg(i, cfg)

    # ---------- 配置持久化 ----------
    def _save_config_now(self):
        save_config(self._collect_config())
        self.lbl_status.setText("配置已保存")

    def _load_config_now(self):
        if QMessageBox.question(self, "加载配置", "确定从已保存的配置恢复当前设置吗?") \
                != QMessageBox.StandardButton.Yes:
            return
        self._load_from_config(load_config())
        self._apply_theme(self.theme)
        self.lbl_status.setText("配置已加载")

    # ---------- 主题 ----------
    def _apply_theme(self, theme):
        """切换亮色/暗色主题: 应用级样式替换 + 局部部件同步。"""
        self.theme = theme
        qss = APP_QSS if theme == "light" else APP_DARK_QSS
        QApplication.instance().setStyleSheet(qss)
        self.setStyleSheet(qss)
        self._apply_theme_parts()

    def _apply_theme_parts(self):
        """应用除窗口级样式外的主题相关部件样式(启动时避免重复抛光)。"""
        theme = self.theme
        self.log_text.setStyleSheet(LOG_STYLES[theme])
        self.log_colors = LOG_COLOR_SETS[theme]
        self.log_box.set_theme(collapsible_qss(theme))
        (self.act_light if theme == "light" else self.act_dark).setChecked(True)
        self._set_status_color(None)
        self._update_upx_marker()

    def _status_default_color(self):
        """状态栏文字默认颜色(按主题)。"""
        return "#a8adb5" if self.theme == "dark" else "#3f4f63"

    def _set_status_color(self, color):
        """设置状态栏文字颜色; color 为 None 时恢复主题默认色。"""
        self.lbl_status.setStyleSheet(
            "color:%s;" % (color or self._status_default_color()))

    # ---------- 日志 ----------
    def _log(self, text, level="normal"):
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.log_colors.get(level, self.log_colors["normal"])))
        if level == "cmd":
            fmt.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(text + "\n", fmt)
        self.log_text.setTextCursor(cursor)
        self.log_text.ensureCursorVisible()

    def _jump_to_first_error(self):
        """在日志里选中并跳转到第一条 FATAL/ERROR 行, 帮助用户快速定位错误。"""
        doc = self.log_text.document()
        keywords = ("fatal", "traceback", "error:", "  error ", "exception")
        for i in range(doc.blockCount()):
            text = doc.block(i).text().lower()
            if any(k in text for k in keywords):
                cursor = QTextCursor(doc)
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                for _ in range(i):
                    cursor.movePosition(QTextCursor.MoveOperation.Down)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                self.log_text.setTextCursor(cursor)
                self.log_text.ensureCursorVisible()
                return

    def _clear_log(self):
        self.log_text.clear()

    def _preview_command(self):
        cmd, blocked = build_command(self._collect_config())
        if not cmd:
            self._log("找不到可用的 Python 解释器(需已安装 Nuitka)", "error")
            return
        if blocked:
            self._log("已忽略 UI 已管控的高级参数: %s (请使用表单对应字段)"
                      % ", ".join(blocked), "warn")
        self._log("========== 命令预览 ==========", "cmd")
        self._log(" ".join(cmd), "cmd")
        self._log("(仅预览, 未执行; 执行完整构建请点击「开始打包」)", "cmd")

    # ---------- 环境检查 ----------
    def _start_env_check(self):
        if self.building:
            return
        self.btn_env.setEnabled(False)
        self.btn_mingw.setEnabled(False)
        self.lbl_status.setText("正在检查环境...")
        self._log("========== 环境检查 ==========", "cmd")
        self._env_worker = EnvWorker()
        self._env_worker.finished.connect(self._on_env_result)
        self._env_worker.start()

    def _on_env_result(self, items):
        errors = 0
        warns = 0
        for name, status, detail, hint in items:
            if status == "ok":
                self._log("%s: %s" % (name, detail), "ok")
            elif status == "warn":
                self._log("%s: %s" % (name, detail), "warn")
                warns += 1
            else:
                self._log("%s: %s" % (name, detail), "error")
                errors += 1
            if hint:
                self._log("  建议: %s" % hint, "warn")

        def status_of(n):
            for it in items:
                if it[0] == n:
                    return it[1]
            return "warn"

        self.env_nuitka_ok = status_of("Nuitka") != "error"
        if os.name == "nt":
            self.env_compiler_ok = any(
                status_of(name) == "ok"
                for name in ("MSVC", "系统 gcc", "MinGW64"))
        else:
            # Linux / macOS: gcc 或 clang 任一 OK 即可
            self.env_compiler_ok = any(
                status_of(name) == "ok"
                for name in ("系统 gcc", "系统 clang"))

        self.btn_env.setEnabled(True)
        if os.name != "nt":
            self.btn_mingw.setText("gcc 安装指引")
            self.btn_mingw.setToolTip("Linux / macOS 使用系统 gcc/clang 编译")
        elif deps.python_requires_msvc():
            self.btn_mingw.setText("安装 MSVC 指引")
            self.btn_mingw.setToolTip("Python 3.13+ 需要 MSVC 编译器")
        else:
            self.btn_mingw.setText("下载 MinGW64")
            self.btn_mingw.setToolTip("")
        self.btn_mingw.setEnabled(not self.env_compiler_ok)
        if errors:
            self.lbl_status.setText("环境检查: 存在 %d 个错误" % errors)
            self._log("环境检查: 存在 %d 个错误, 请按上方建议修复 (另有 %d 个警告)。"
                      % (errors, warns), "error")
        else:
            self.lbl_status.setText("环境检查: 通过 (警告 %d 个)" % warns)
            self._log("环境检查: 通过 ✔ (%d 个警告)" % warns, "ok")

    # ---------- 任务执行(后台线程) ----------
    def _start_worker(self, target, *args):
        self._worker = BuildWorker()
        queue = WorkerQueue(self._worker)
        self._worker.command.connect(lambda t: self._log(t, "cmd"))
        self._worker.output.connect(self._on_output)
        self._worker.error.connect(lambda t: self._log(t, "error"))
        self._worker.ok.connect(lambda t: self._log(t, "ok"))
        self._worker.done.connect(self._on_task_done)
        self._set_building(True)
        self._worker.start(target, queue, self.stop_event, *args)

    def _start_build(self):
        if not self.ed_script.text().strip():
            self.ed_script.setText(DEFAULT_SCRIPT)  # 未填主脚本时默认打包本工具自身
        cfg = self._collect_config()
        script = cfg["script"]
        if not os.path.isfile(script):
            QMessageBox.critical(self, "错误", "脚本文件不存在:\n%s" % script)
            return
        if not script.lower().endswith(".py"):
            QMessageBox.warning(self, "提示", "请选择 .py 脚本文件。")
            return
        if cfg.get("icon") and not os.path.isfile(cfg["icon"]):
            QMessageBox.critical(
                self, "错误",
                "图标文件不存在:\n%s\n\n请到「基本信息」→ 图标, 重新选择有效图标文件。"
                % cfg["icon"])
            return
        if os.name == "nt" and cfg.get("icon") and not cfg["icon"].lower().endswith(".ico"):
            # Windows 下 --windows-icon-from-ico 只接受 .ico (多尺寸打包在一个文件里)
            QMessageBox.warning(
                self, "提示",
                "Windows 平台建议使用 .ico 格式图标 (含多种尺寸)。\n"
                "当前选择非 .ico 文件, Nuitka 只会把它作为数据文件打进去, 不会嵌入 PE 图标。")
        save_config(cfg)
        self.stop_event.clear()
        self._current_task = "build"
        self._log("========== 开始打包 ==========", "cmd")
        self._start_worker(run_build, cfg)

    def _download_mingw(self):
        if self.building:
            return
        self.stop_event.clear()
        self._current_task = "mingw"
        self._log("========== 下载 MinGW64 ==========", "cmd")
        self._start_worker(deps.run_mingw_download)

    def _cancel_build(self):
        self.stop_event.set()
        self.lbl_status.setText("正在取消...")

    def _set_building(self, building):
        self.building = building
        self.btn_start.setEnabled(not building)
        self.btn_cancel.setEnabled(building)
        self.btn_env.setEnabled(not building)
        self.btn_mingw.setEnabled(not building and not self.env_compiler_ok)
        if building:
            self._set_status_color(None)
            self.progress.setRunning(True)
            self.lbl_status.setText("正在处理, 请稍候...")
        else:
            self.progress.setRunning(False)

    def _on_output(self, line):
        # 行级别智能分级: stdout 里的 FATAL/ERROR/WARNING 自动上色
        level = _classify_line_level(line)
        self._log(line, level)
        low = line.lower()

        # --- 阶段关键字映射: 命中即更新状态文字 + 百分比 ---
        for _kw, _label, pct in PROGRESS_STEPS:
            if _kw in low:
                self.lbl_status.setText("%s (%d%%)" % (_label, pct))
                break

    def _on_task_done(self, code):
        self._set_building(False)
        if self._current_task == "mingw":
            self._on_mingw_done(code)
        else:
            self._on_build_done(code)

    def _on_build_done(self, code):
        if code == 0:
            self._set_status_color("#34C759")
            QTimer.singleShot(2000, lambda: self._set_status_color(None))
            self.lbl_status.setText("打包完成 ✔")
            self._log("========== 打包成功 ==========", "ok")
            QMessageBox.information(self, "完成", "打包成功! 产物已生成到输出目录。")
        elif code == -2:
            self._set_status_color(None)
            self.lbl_status.setText("已取消")
            self._log("========== 已取消 ==========", "error")
        else:
            self._set_status_color("#FF3B30")
            self.lbl_status.setText("打包失败")
            self._log("========== 打包失败 (退出码 %s) ==========" % code, "error")
            # 自动跳转到日志第一条 FATAL/ERROR 行, 帮助快速定位
            self._jump_to_first_error()
            # 从日志中自动诊断失败原因, 给出针对性提示
            findings = analyze_failure(self.log_text.toPlainText())
            if (deps.python_requires_msvc() and not deps.find_msvc()
                    and not any("MSVC" in title for title, _ in findings)):
                findings.append(
                    ("缺少 MSVC 编译器",
                     "安装 Microsoft C++ Build Tools: "
                     "winget install Microsoft.VisualStudio.2022.BuildTools"))
            for title, fix in findings[:3]:
                self._log("诊断: %s" % title, "error")
                self._log("建议: %s" % fix, "warn")
            if not findings:
                self._log("未能识别具体原因, 请查看上方日志中的 FATAL/ERROR 行。", "warn")
            lines = ["打包失败 (退出码 %s)。" % code, ""]
            if findings:
                for title, fix in findings[:2]:
                    lines.append("• %s" % title)
                    lines.append("  建议: %s" % fix)
            else:
                lines.append("未识别到具体原因, 请查看日志中的错误信息。")
            QMessageBox.critical(self, "打包失败", "\n".join(lines))

    def _on_mingw_done(self, code):
        self._log("MinGW64 下载流程结束。", "cmd")
        QTimer.singleShot(400, self._start_env_check)

    # ---------- 其他 ----------
    def _show_about(self):
        QMessageBox.about(
            self, "关于",
            "Nuitka 打包工具 (PySide6)\n\n"
            "基于 PySide6 的 Nuitka GUI, 打包任务在后台线程执行,\n"
            "界面保持响应。\n\n"
            "依赖: pip install nuitka PySide6\n\n"
            "支持: 单文件/单目录/模块打包、插件、数据文件、\n"
            "Windows 版本信息、附加参数、环境检查等。")

    def closeEvent(self, event):
        if self.building:
            if QMessageBox.question(self, "确认", "打包正在进行, 确定退出吗?") \
                    != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # 必须在本进程退出前杀掉 Nuitka/scons 进程树:
            # 后台线程是 daemon, 窗口关闭后不会再跑 run_process 里的取消逻辑
            stop_active_builds(self.stop_event)
        save_config(self._collect_config())
        event.accept()

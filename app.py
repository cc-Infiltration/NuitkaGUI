# -*- coding: utf-8 -*-
#Nuitka 打包工具 GUI 主界面 (PySide6)

import os
import threading

from PySide6.QtCore import QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QRegularExpressionValidator,
    QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

import deps
from builder import build_command, run_build
from config import DEFAULT_CONFIG, load_config, save_config

# Nuitka 插件名区分大小写
PLUGIN_OPTIONS = [
    "tk-inter", "pyqt5", "pyqt6", "pyside2", "pyside6",
    "upx", "no-qt", "dll-files", "anti-bloat",
    "pygame", "trio", "glfw", "loguru",
]

MODE_OPTIONS = (
    ("onefile", "单文件打包 (--onefile)"),
    ("onedir", "单目录打包 (--standalone)"),
    ("module", "打包为模块 (--module)"),
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

# Nuitka 输出中的阶段关键字 -> (显示文本, 进度百分比), 按进度从低到高排列
PROGRESS_STEPS = (
    ("download", "下载编译器/依赖", 5),
    ("compatibility check", "兼容性检查", 8),
    ("python level compilation", "Python 编译优化", 40),
    ("generating source code", "生成 C 源码", 55),
    ("running data composer", "生成数据", 62),
    ("starting c compilation", "C 编译 (最耗时)", 72),
    ("completed c compilation", "C 编译完成", 85),
    ("linking", "链接", 90),
    ("creating", "生成产物", 95),
    ("successfully", "完成", 100),
)

# 日志区样式与文字颜色(按主题)
LOG_STYLES = {
    "light": ("QPlainTextEdit{background:#ffffff;color:#1f2328;"
              "font-family:Consolas;font-size:9pt;border:1px solid #d5dce5;"
              "border-radius:6px;}"),
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

# 全局清爽浅色主题
APP_QSS = """
QMainWindow { background: #f4f6f9; }
QWidget { font-family: "Microsoft YaHei UI","Segoe UI",sans-serif; font-size: 9.5pt; color: #1f2328; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #e3e8ef;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 6px 6px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    top: 4px;
    padding: 0 4px;
    color: #2f3b4d;
    font-weight: bold;
}
QLabel { color: #3d4a5c; }
QLineEdit, QComboBox, QSpinBox {
    background: #ffffff;
    border: 1px solid #d5dce5;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 18px;
    selection-background-color: #2d8cf0;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #2d8cf0; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #d5dce5;
    selection-background-color: #e8f1fd;
    selection-color: #2d8cf0;
    outline: 0;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #d5dce5;
    border-radius: 5px;
    padding: 5px 14px;
    color: #2f3b4d;
}
QPushButton:hover { background: #f0f4fa; border-color: #b8c6d9; }
QPushButton:pressed { background: #e3ecf7; }
QPushButton:disabled { color: #b0b8c4; background: #f2f4f7; border-color: #e8ecf2; }
QPushButton#primaryBtn {
    background: #2d8cf0;
    border: none;
    color: #ffffff;
    padding: 7px 24px;
    font-weight: bold;
}
QPushButton#primaryBtn:hover { background: #237fe0; }
QPushButton#primaryBtn:pressed { background: #1b6fc9; }
QPushButton#primaryBtn:disabled { background: #a8c8ee; color: #eaf2fc; }
QTabWidget::pane {
    border: 1px solid #e3e8ef;
    border-radius: 8px;
    background: #ffffff;
    top: -1px;
}
QTabBar::tab {
    background: #eef1f5;
    border: 1px solid #e3e8ef;
    border-bottom: none;
    padding: 6px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #5a6a7e;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #2d8cf0;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { background: #f5f8fc; }
QCheckBox, QRadioButton { color: #3d4a5c; spacing: 6px; }
QProgressBar {
    border: 1px solid #d5dce5;
    border-radius: 6px;
    background: #eef1f5;
    text-align: center;
    color: #2f3b4d;
}
QProgressBar::chunk { background: #2d8cf0; border-radius: 6px; }
QListWidget {
    background: #ffffff;
    border: 1px solid #d5dce5;
    border-radius: 5px;
    outline: 0;
}
QListWidget::item { padding: 2px 4px; }
QListWidget::item:selected { background: #e8f1fd; color: #2d8cf0; }
QMenuBar { background: transparent; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #e8f1fd; border-radius: 5px; }
QMenu { background: #ffffff; border: 1px solid #e3e8ef; }
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: #e8f1fd; color: #2d8cf0; }
QMessageBox {
    background: #ffffff;
}
QMessageBox QLabel {
    color: #1f2328;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #c3ccd8; border-radius: 5px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #a8b4c4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #c3ccd8; border-radius: 5px; min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #a8b4c4; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""

# 全局暗色主题
APP_DARK_QSS = """
QMainWindow { background: #1e1f22; }
QWidget { font-family: "Microsoft YaHei UI","Segoe UI",sans-serif; font-size: 9.5pt; color: #e6e6e6; }
QGroupBox {
    background: #2b2d31;
    border: 1px solid #3f4248;
    border-radius: 8px;
    margin-top: 14px;
    padding: 10px 6px 6px 6px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    top: 4px;
    padding: 0 4px;
    color: #f2f3f5;
    font-weight: bold;
}
QLabel { color: #d0d4da; }
QLineEdit, QComboBox, QSpinBox {
    background: #2f3136;
    border: 1px solid #4a4d55;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 18px;
    color: #e6e6e6;
    selection-background-color: #2d8cf0;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #4d9fff; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #2b2d31;
    border: 1px solid #4a4d55;
    selection-background-color: #2d4d78;
    selection-color: #ffffff;
    outline: 0;
}
QPushButton {
    background: #3a3d43;
    border: 1px solid #4a4d55;
    border-radius: 5px;
    padding: 5px 14px;
    color: #e6e6e6;
}
QPushButton:hover { background: #44474e; border-color: #5a5e66; }
QPushButton:pressed { background: #50545c; }
QPushButton:disabled { color: #6f737b; background: #313338; border-color: #3a3d43; }
QPushButton#primaryBtn {
    background: #2d8cf0;
    border: none;
    color: #ffffff;
    padding: 7px 24px;
    font-weight: bold;
}
QPushButton#primaryBtn:hover { background: #4d9fff; }
QPushButton#primaryBtn:pressed { background: #1b6fc9; }
QPushButton#primaryBtn:disabled { background: #2b4a6e; color: #9db4cc; }
QTabWidget::pane {
    border: 1px solid #3f4248;
    border-radius: 8px;
    background: #2b2d31;
    top: -1px;
}
QTabBar::tab {
    background: #26272b;
    border: 1px solid #3f4248;
    border-bottom: none;
    padding: 6px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #a8adb5;
}
QTabBar::tab:selected {
    background: #2b2d31;
    color: #4d9fff;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { background: #303238; }
QCheckBox, QRadioButton { color: #d0d4da; spacing: 6px; }
QProgressBar {
    border: 1px solid #4a4d55;
    border-radius: 6px;
    background: #313338;
    text-align: center;
    color: #e6e6e6;
}
QProgressBar::chunk { background: #2d8cf0; border-radius: 6px; }
QListWidget {
    background: #2f3136;
    color: #e6e6e6;
    border: 1px solid #4a4d55;
    border-radius: 5px;
    outline: 0;
}
QListWidget::item { padding: 2px 4px; }
QListWidget::item:selected { background: #2d4d78; color: #ffffff; }
QMenuBar { background: transparent; }
QMenuBar::item { padding: 5px 10px; background: transparent; color: #d0d4da; }
QMenuBar::item:selected { background: #3a3d43; border-radius: 5px; }
QMenu { background: #2b2d31; border: 1px solid #3f4248; color: #e6e6e6; }
QMenu::item { padding: 5px 22px; }
QMenu::item:selected { background: #2d4d78; color: #ffffff; }
QMessageBox { background: #2b2d31; }
QMessageBox QLabel { color: #e6e6e6; background: transparent; }
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #4a4d55; border-radius: 5px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #5a5e66; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #4a4d55; border-radius: 5px; min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #5a5e66; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
"""


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


class ListEditor(QGroupBox):
    """带添加/删除的列表编辑器, 支持单个输入框或"来源=目标"双输入框。"""

    def __init__(self, title, second_label=None, parent=None):
        super().__init__(title, parent)
        self._items = []
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        row = QHBoxLayout()
        self._entry = QLineEdit()
        row.addWidget(self._entry, 1)
        if second_label:
            self._entry2 = QLineEdit()
            self._entry2.setPlaceholderText(second_label)
            row.addWidget(self._entry2, 1)
        else:
            self._entry2 = None
        layout.addLayout(row)

        self._list = QListWidget()
        self._list.setMaximumHeight(90)
        layout.addWidget(self._list)

        btns = QHBoxLayout()
        add_btn = QPushButton("添加")
        rm_btn = QPushButton("删除选中")
        add_btn.clicked.connect(self._add)
        rm_btn.clicked.connect(self._remove)
        btns.addWidget(add_btn)
        btns.addWidget(rm_btn)
        btns.addStretch()
        layout.addLayout(btns)

    def _add(self):
        a = self._entry.text().strip()
        if not a:
            return
        if self._entry2 is not None:
            b = self._entry2.text().strip()
            item = "%s=%s" % (a, b) if b else a
        else:
            item = a
        self._items.append(item)
        self._list.addItem(item)
        self._entry.clear()
        if self._entry2 is not None:
            self._entry2.clear()

    def _remove(self):
        for row in reversed(self._list.selectedIndexes()):
            idx = row.row()
            self._list.takeItem(idx)
            del self._items[idx]

    def set_items(self, items):
        self._list.clear()
        self._items = list(items)
        for item in self._items:
            self._list.addItem(item)

    def get_items(self):
        return list(self._items)


class NuitkaGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Nuitka 打包工具")
        self.resize(1060, 820)
        self.setMinimumSize(940, 700)

        self.stop_event = threading.Event()
        self.building = False
        self._worker = None
        self._env_worker = None
        self._current_task = None
        self.env_nuitka_ok = False
        self.env_compiler_ok = False
        self.theme = "light"
        self.log_colors = LOG_COLOR_SETS["light"]

        self._build_ui()
        self._build_menu()
        self._load_from_config(load_config())
        self._apply_theme(self.theme)
        # 启动后自动做一次环境检查(后台线程, 不阻塞界面)
        QTimer.singleShot(400, self._start_env_check)

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
        grid.addWidget(label("控制台:"), 3, 0)
        grid.addLayout(console_row, 3, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(top)

        # 启用插件 (独立板块, 位于项目区与选项卡之间)
        root.addWidget(self._build_plugin_group())

        # 选项卡
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "基本选项")
        self.tabs.addTab(self._build_data_tab(), "数据与模块")
        self.tabs.addTab(self._build_win_tab(), "Windows 信息")
        self.tabs.addTab(self._build_advanced_tab(), "高级")
        root.addWidget(self.tabs, 2)

        # 日志区
        log_group = QGroupBox("构建日志")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 16, 10, 10)
        log_layout.setSpacing(6)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(130)
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
        root.addWidget(log_group, 1)

        # 底部操作栏
        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(180)
        self.progress.setFixedHeight(22)
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#5a6a7e;")
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
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollArea>QWidget>QWidget{background:transparent;}")
        content = QWidget()
        scroll.setWidget(content)
        return scroll, content

    def _build_plugin_group(self):
        plugin_group = QGroupBox("启用插件 (可多选)")
        grid = QGridLayout(plugin_group)
        grid.setContentsMargins(12, 16, 12, 10)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        cols = 5
        self.plugin_checks = {}
        for i, name in enumerate(PLUGIN_OPTIONS):
            cb = QCheckBox(name)
            self.plugin_checks[name] = cb
            grid.addWidget(cb, i // cols, i % cols)
        return plugin_group

    def _build_basic_tab(self):
        scroll, content = self._scrollable()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        # 图标
        icon_row = QHBoxLayout()
        icon_row.setSpacing(8)
        icon_row.addWidget(QLabel("图标 (.ico):"))
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
        hint.setStyleSheet("color:#8a95a5;")
        opt_form.addWidget(hint, 1, 2, 1, 2)
        layout.addWidget(opt_group)
        layout.addStretch()
        return scroll

    def _build_data_tab(self):
        scroll, content = self._scrollable()
        layout = QGridLayout(content)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(8)

        self.ed_data_dirs = ListEditor("数据目录 (来源=目标子路径)", second_label="目标子路径")
        self.ed_data_files = ListEditor("数据文件 (来源=目标路径)", second_label="目标路径")
        self.ed_pkgs = ListEditor("包含包 (--include-package)")
        self.ed_mods = ListEditor("包含模块 (--include-module)")
        self.ed_excludes = ListEditor("排除导入 (--nofollow-import-to)")

        layout.addWidget(self.ed_data_dirs, 0, 0)
        layout.addWidget(self.ed_data_files, 0, 1)
        layout.addWidget(self.ed_pkgs, 1, 0)
        layout.addWidget(self.ed_mods, 1, 1)
        layout.addWidget(self.ed_excludes, 2, 0, 1, 2)
        layout.setRowStretch(3, 1)
        return scroll

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
        hint.setStyleSheet("color:#8a95a5;")
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
        hint.setStyleSheet("color:#8a95a5;")
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
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图标", "", "图标文件 (*.ico);;所有文件 (*.*)")
        if path:
            self.ed_icon.setText(path)

    # ---------- 配置 <-> 界面 ----------
    def _collect_config(self):
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({
            "script": self.ed_script.text().strip(),
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
            "include_packages": self.ed_pkgs.get_items(),
            "include_modules": self.ed_mods.get_items(),
            "exclude_modules": self.ed_excludes.get_items(),
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
        self.ed_script.setText(cfg.get("script", ""))
        self.ed_output_dir.setText(cfg.get("output_dir", ""))
        self.ed_output_name.setText(cfg.get("output_filename", ""))
        self.cb_mode.setCurrentText(MODE_TO_LABEL.get(cfg.get("mode", "onefile"),
                                                      MODE_TO_LABEL["onefile"]))
        self.rb_console_yes.setChecked(bool(cfg.get("console", True)))
        self.rb_console_no.setChecked(not bool(cfg.get("console", True)))
        self.ed_icon.setText(cfg.get("icon", ""))
        saved_plugins = {p.lower() for p in cfg.get("plugins", [])}
        for name, cb in self.plugin_checks.items():
            cb.setChecked(name in saved_plugins)
        self.cb_lto.setCurrentText(LTO_TO_LABEL.get(cfg.get("lto", "auto"),
                                                    LTO_TO_LABEL["auto"]))
        self.spin_jobs.setValue(int(cfg.get("jobs") or 4))
        self.chk_remove.setChecked(bool(cfg.get("remove_output", False)))
        self.ed_data_dirs.set_items(cfg.get("data_dirs", []))
        self.ed_data_files.set_items(cfg.get("data_files", []))
        self.ed_pkgs.set_items(cfg.get("include_packages", []))
        self.ed_mods.set_items(cfg.get("include_modules", []))
        self.ed_excludes.set_items(cfg.get("exclude_modules", []))
        self.ed_company.setText(cfg.get("company_name", ""))
        self.ed_product.setText(cfg.get("product_name", ""))
        self.ed_file_version.setText(cfg.get("file_version", ""))
        self.ed_product_version.setText(cfg.get("product_version", ""))
        self.ed_description.setText(cfg.get("file_description", ""))
        self.ed_copyright.setText(cfg.get("copyright", ""))
        self.ed_extra.setText(cfg.get("extra_args", ""))
        self.theme = cfg.get("theme", "light")

    # ---------- 配置持久化 ----------
    def _save_config_now(self):
        save_config(self._collect_config())
        self.lbl_status.setText("配置已保存")

    def _load_config_now(self):
        if QMessageBox.question(self, "加载配置", "确定从已保存的配置恢复当前设置吗?"):
            self._load_from_config(load_config())
            self._apply_theme(self.theme)
            self.lbl_status.setText("配置已加载")

    # ---------- 主题 ----------
    def _apply_theme(self, theme):
        """切换亮色/暗色主题, 并同步日志区样式与菜单选中态。"""
        self.theme = theme
        self.setStyleSheet(APP_QSS if theme == "light" else APP_DARK_QSS)
        self.log_text.setStyleSheet(LOG_STYLES[theme])
        self.log_colors = LOG_COLOR_SETS[theme]
        (self.act_light if theme == "light" else self.act_dark).setChecked(True)

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

    def _clear_log(self):
        self.log_text.clear()

    def _preview_command(self):
        cmd = build_command(self._collect_config())
        if not cmd:
            return
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
        self.env_compiler_ok = any(
            status_of(name) == "ok"
            for name in ("MSVC", "系统 gcc", "MinGW64"))

        self.btn_env.setEnabled(True)
        if deps.python_requires_msvc():
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
        cfg = self._collect_config()
        if not cfg["script"]:
            QMessageBox.warning(self, "提示", "请先选择要打包的主脚本。")
            return
        if not os.path.isfile(cfg["script"]):
            QMessageBox.critical(self, "错误", "脚本文件不存在:\n%s" % cfg["script"])
            return
        if not cfg["script"].lower().endswith(".py"):
            QMessageBox.warning(self, "提示", "请选择 .py 脚本文件。")
            return
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
            self.progress.setValue(0)
            self.lbl_status.setText("正在处理, 请稍候...")
        else:
            self.progress.setValue(0)

    def _on_output(self, line):
        self._log(line)
        low = line.lower()
        for _kw, _label, pct in PROGRESS_STEPS:
            if _kw in low:
                self.progress.setValue(pct)
                self.lbl_status.setText("处理进度: %d%%" % pct)
                break

    def _on_task_done(self, code):
        self._set_building(False)
        if self._current_task == "mingw":
            self._on_mingw_done(code)
        else:
            self._on_build_done(code)

    def _on_build_done(self, code):
        if code == 0:
            self.progress.setValue(100)
            self.lbl_status.setText("打包完成 ✔")
            self._log("========== 打包成功 ==========", "ok")
            QMessageBox.information(self, "完成", "打包成功! 产物已生成到输出目录。")
        elif code == -2:
            self.lbl_status.setText("已取消")
            self._log("========== 已取消 ==========", "error")
        else:
            self.lbl_status.setText("打包失败")
            self._log("========== 打包失败 (退出码 %s) ==========" % code, "error")
            if deps.python_requires_msvc() and not deps.find_msvc():
                self._log("提示: Python 3.13+ 需要 MSVC 编译器, 请安装 Build Tools: "
                          "winget install Microsoft.VisualStudio.2022.BuildTools", "warn")
            QMessageBox.critical(
                self, "失败",
                "打包失败, 退出码 %s。请查看日志。\n"
                "若 Nuitka 报「unknown option」, 请升级 Nuitka: pip install -U nuitka" % code)

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
        save_config(self._collect_config())
        event.accept()

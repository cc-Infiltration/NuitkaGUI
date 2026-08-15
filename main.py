# -*- coding: utf-8 -*-
"""Nuitka 打包工具入口"""

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from modules.app import NuitkaGUI


def _find_icon():
    """定位 a.ico: 源码运行在脚本目录; 打包产物运行时图标由构建命令的
    --include-data-files 打进产物(与 sys.executable 同目录)。"""
    candidates = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "a.ico")]
    if sys.executable:
        candidates.append(
            os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "a.ico"))
    candidates.append(os.path.abspath("a.ico"))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Nuitka 打包工具")
    app.setOrganizationName("NuitkaGUI")

    # 窗口/任务栏图标
    icon_path = _find_icon()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    win = NuitkaGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

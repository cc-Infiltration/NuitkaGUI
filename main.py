# -*- coding: utf-8 -*-
"""Nuitka 打包工具入口"""

import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import NuitkaGUI


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Nuitka 打包工具")
    app.setOrganizationName("NuitkaGUI")

    # 窗口/任务栏图标 (a.ico 位于程序目录)
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "a.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    win = NuitkaGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

# NuitkaGUI

Nuitka 的图形化打包工具，**PySide6** 开发，Python 程序一键打包。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)]()
[![GUI](https://img.shields.io/badge/GUI-PySide6-green.svg)]()
[![Version](https://img.shields.io/badge/Version-1.1.0-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 特性

- **多模式打包**：单文件 (`--onefile`)、单目录 (`--standalone`)、模块 (`--module`)
- **插件多选**：PySide6 / PyQt5 / PyQt6 / tk-inter / upx 复选框自由组合
- **数据与模块**：包含数据目录/文件、包含包/模块、排除导入
- **Windows 元数据**：公司/产品名、版本号、描述、版权（版本号自动校验）
- **阶段进度条**：实时解析 Nuitka 输出，按 下载→编译→链接→产物 推进
- **不卡顿并发**：打包/下载/环境检查均在后台线程，Qt 信号槽回传日志
- **跨平台**：Windows / Linux / macOS 自动适配构建命令
- **安全加固**：config.json SHA-256 校验、TOCTOU 二次校验、命令回显脱敏

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

| 依赖 | 安装 |
|------|------|
| Python | 3.10+（3.13.7 已验证） |
| Nuitka | 含在 requirements.txt |
| PySide6 | 含在 requirements.txt |

> **C 编译器**：Python 3.13+ 需 MSVC (`winget install Microsoft.VisualStudio.2022.BuildTools`)；3.12 及以下首次打包自动下载 MinGW64。

## 界面预览

| 暗色主题 | 亮色主题 |
| --- | --- |
| ![暗色主题](MdImages/主界面Dark.png) | ![亮色主题](MdImages/主界面ling.png) |

## 打包本项目

```bash
python -m nuitka --standalone --onefile --enable-plugin=pyside6 ^
  --windows-console-mode=disable --windows-icon-from-ico=a.ico ^
  --include-data-files=a.ico=a.ico --output-filename=NuitkaGUI ^
  --output-dir=dist --jobs=4 --assume-yes-for-downloads main.py
```

## FAQ

- **`unknown plug-in 'PySide6' in wrong case`？** → Nuitka 插件名小写（`pyside6`），工具已自动处理
- **`Invalid version number --file-version='V1.0.0'`？** → 版本号必须纯数字点分，输入框已自动清洗前缀
- **Python 3.13 为什么没 MinGW64 下载？** → 3.13+ 不支持 MinGW64，需安装 MSVC

## 更新日志
[详细日志](https://github.com/cc-Infiltration/NuitkaGUI/releases/tag/1.1.0)

## License

[MIT](LICENSE)

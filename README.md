# NuitkaGUI

[Nuitka](https://nuitka.net/) 的图形化打包工具，基于 **PySide6**，把 Python 程序一键打包为 Windows / Linux / macOS 可执行文件。

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)]()
[![GUI](https://img.shields.io/badge/GUI-PySide6-green.svg)]()
[![Version](https://img.shields.io/badge/Version-1.1.0-brightgreen.svg)]()
[![License](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![CI](https://github.com/cc-Infiltration/NuitkaGUI/actions/workflows/python-app.yml/badge.svg)](https://github.com/cc-Infiltration/NuitkaGUI/actions)

## 功能

- **三种打包模式**：单文件 / 单目录 / 模块
- **插件自动发现**：按类别分组展示，升级 Nuitka 自动适配
- **数据与模块**：数据目录/文件、包含包、排除导入；智能计算目标路径，自动规避冲突
- **Windows 元数据**：公司/产品名、版本、描述、版权
- **环境自检**：启动自动检查 Python、Nuitka、C 编译器；MinGW64 一键下载（Python ≤ 3.12），3.13+ 引导 MSVC 安装
- **失败自动诊断**：17 类常见规则给出针对性修复建议
- **日志分级上色**：错误红 / 警告黄 / 正常绿，命令回显脱敏
- **不卡顿**：后台线程执行，取消时进程树干净退出
- **安全加固**：配置 SHA-256 完整性校验、打包前二次文件校验、高级参数黑名单、日志脱敏

## 界面预览

| 暗色主题 | 亮色主题 |
| --- | --- |
| ![暗色主题](MdImages/主界面Dark.png) | ![亮色主题](MdImages/主界面ling.png) |

## 快速开始

**环境要求**：Python 3.10+、Nuitka `>=4.2.1,<4.3.0`、PySide6 `>=6.7.0`；Python 3.13+ 需 MSVC（`winget install Microsoft.VisualStudio.2022.BuildTools`），3.12 及以下首次打包自动下载 MinGW64。

```bash
pip install -r requirements.txt
python main.py
```

## 使用流程

1. 选主脚本、输出目录、打包模式
2. 配图标、LTO、并行任务数
3. 按需勾选插件、数据、高级选项
4. 点 **开始打包**，失败时按日志区建议修复

配置保存在 `~/.nuitka_gui/config.json`，自动保存恢复。

## 打包本项目

```bash
# Windows (PowerShell)
python -m nuitka --standalone --onefile --enable-plugin=pyside6 `
  --windows-console-mode=disable --windows-icon-from-ico=a.ico `
  --include-data-files=a.ico=a.ico --include-data-dir=styles=styles `
  --output-filename=NuitkaGUI --output-dir=dist --jobs=4 `
  --assume-yes-for-downloads main.py

# Linux / macOS
python -m nuitka --standalone --onefile --enable-plugin=pyside6 \
  --include-data-dir=styles=styles \
  --output-filename=NuitkaGUI --output-dir=dist --jobs=4 \
  --assume-yes-for-downloads main.py
```

> `--include-data-dir=styles=styles` 必须保留，否则主题切换无效。

## 项目结构

```text
NuitkaGUI/
├── main.py            # 入口
├── modules/
│   ├── app.py         # GUI 主界面
│   ├── builder.py     # Nuitka 命令构造与执行
│   ├── config.py      # 配置持久化
│   └── deps.py        # 环境检查与编译器探测
├── styles/            # 亮/暗主题 QSS
├── MdImages/          # README 截图
├── a.ico              # 应用图标
└── requirements.txt
```

## 常见问题

1. **Scons 编译锁超时？** 关掉其他打包窗口；仍失败删除 `output_dir/.nuitka_cache` 后重试。
2. **Python 3.13 Qt 插件报错？** 工具已自动处理 `QT_PLUGIN_PATH`，无需干预。
3. **主题切换无效？** 确认打包命令包含 `--include-data-dir=styles=styles`。

## 更新日志

[GitHub Releases](https://github.com/cc-Infiltration/NuitkaGUI/releases)

## License

[GNU General Public License v3.0](LICENSE)

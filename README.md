# NuitkaGUI

Nuitka 的图形化打包工具，使用 **PySide6** 开发，为 Python 程序提供可视化的一键打包能力。

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg)]()
[![GUI](https://img.shields.io/badge/GUI-PySide6-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## 特性

- 🚀 **多种打包模式**：单文件 (`--onefile`)、单目录 (`--standalone`)、模块 (`--module`)
- 🧩 **插件多选**：tk-inter、PySide6、PyQt5/6、upx 等常用 Nuitka 插件，复选框自由组合
- 📦 **数据与模块管理**：包含数据目录/文件、包含包/模块、排除导入
- 🏷️ **Windows 元数据**：公司名、产品名、文件/产品版本、描述、版权（写入 exe 属性，版本号输入框自动校验格式）
- 🔍 **环境检查**：自动检测 Python / Nuitka / C 编译器（MSVC / MinGW64），提供缺失项修复建议
- 🧵 **不卡顿的并发**：打包、下载、环境检查均在后台线程执行，通过 Qt 信号槽回传日志，界面始终响应
- 📊 **阶段进度条**：实时解析 Nuitka 输出，按阶段（下载→编译→链接→产物）显示进度百分比
- 🎨 **亮色/暗色主题**：菜单「视图」一键切换，选择自动保存
- ⚙️ **配置持久化**：所有设置自动保存到 `~/.nuitka_gui/config.json`，可随时保存/加载

## 环境要求

| 依赖 | 说明 |
| --- | --- |
| Python | 3.10+（本项目在 3.13.7 验证） |
| Nuitka | `pip install nuitka` |
| PySide6 | `pip install PySide6` |

> **C 编译器说明**
> - **Python 3.13+**：Nuitka 不支持 MinGW64，需安装 **Microsoft C++ Build Tools**（MSVC），
>   命令行安装：`winget install Microsoft.VisualStudio.2022.BuildTools`
> - **Python 3.12 及以下**：首次打包时 Nuitka 会自动下载 MinGW64（工具默认开启 `--assume-yes-for-downloads` 自动确认）

## 安装与启动

```bash
# 1. 安装依赖
pip install nuitka PySide6

# 2. 启动
python main.py
```

## 使用说明

1. **项目区**：选择主脚本（`.py`）、输出目录、输出文件名、打包模式、控制台保留/隐藏
2. **启用插件**：勾选需要的 Nuitka 插件（可多选）
3. **选项卡**：
   - 基本选项：图标 (.ico)、LTO、并行任务数、清理旧构建缓存
   - 数据与模块：数据目录/文件、包含包/模块、排除导入
   - Windows 信息：文件属性元数据（公司、产品、版本号等）
   - 高级：附加 Nuitka 参数
4. **环境检查**：首次使用建议点击「环境检查」，确认 Nuitka 与编译器就绪
5. **开始打包**：点击后后台执行，日志区实时输出、进度条按阶段推进，可随时取消

## 打包本项目为可执行文件

```bash
python -m nuitka --standalone --onefile --enable-plugin=pyside6 \
  --windows-console-mode=disable --windows-icon-from-ico=a.ico \
  --include-data-files=a.ico=a.ico --output-filename=NuitkaGUI \
  --output-dir=dist --jobs=4 --assume-yes-for-downloads main.py
```

产物：`dist/NuitkaGUI.exe`（单文件、无控制台窗口、内置图标）。

## 项目结构

```
NuitkaGUI/
├── main.py       # 程序入口（QApplication + 图标 + 窗口）
├── app.py        # PySide6 GUI 主界面（主题、布局、信号槽并发）
├── builder.py    # Nuitka 命令构造与子进程执行
├── deps.py       # 环境检查（Nuitka / MSVC / MinGW64 检测与修复建议）
├── config.py     # 配置 JSON 持久化
├── a.ico         # 程序图标
└── README.md
```

## 常见问题

**Q：打包报 `unknown plug-in 'PySide6' in wrong case`？**
A：Nuitka 插件名区分大小写，需使用小写（`pyside6`）。本工具插件列表已使用官方小写名。

**Q：报 `Invalid version number --file-version='V1.0.0'`？**
A：Windows 版本号必须是数字点分格式。输入框已限制只能输入数字与点，旧配置中的 `V` 前缀会被自动清洗。

**Q：Python 3.13 下「下载 MinGW64」按钮？**
A：Python 3.13+ 不支持 MinGW64，按钮自动变为「安装 MSVC 指引」，请安装 Microsoft C++ Build Tools 后重新运行环境检查。

## License

[MIT](LICENSE)

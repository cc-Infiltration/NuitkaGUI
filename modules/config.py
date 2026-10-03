# -*- coding: utf-8 -*-
"""配置的保存与加载(JSON), 存放在用户目录 ~/.nuitka_gui/config.json。"""

import hashlib
import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nuitka_gui")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

# 主脚本未填写时的默认目标: 本工具自身入口 (项目根目录的 main.py)
DEFAULT_SCRIPT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"))

DEFAULT_CONFIG = {
    "script": "",
    "output_dir": "",
    "output_filename": "",
    "mode": "onefile",           # onefile / onedir / module
    "console": True,
    "icon": "",
    "plugins": [],
    "lto": "auto",               # auto / yes / no
    "jobs": 4,
    "remove_output": False,
    "data_dirs": [],
    "data_files": [],
    "include_packages": [],
    "include_modules": [],
    "exclude_modules": [],
    "company_name": "",
    "product_name": "",
    "file_version": "",
    "product_version": "",
    "file_description": "",
    "copyright": "",
    "extra_args": "",
    "theme": "light",            # light / dark
    "custom_compiler_dirs": [],  # 用户手动指定的编译器搜索目录 (自定义 VS/MinGW 安装路径)
}


def _sha256_of_bytes(data):
    """计算数据的 SHA-256 hex 摘要, 用于配置文件完整性校验。"""
    return hashlib.sha256(data).hexdigest()


def load_config():
    """读取配置, 带 SHA-256 完整性校验。

    - 校验和缺失或不匹配 → 回退到默认配置 (可能被篡改或版本升级)
    - JSON 损坏 → 回退到默认配置
    """
    cfg = dict(DEFAULT_CONFIG)
    if not os.path.isfile(CONFIG_PATH):
        return cfg
    try:
        with open(CONFIG_PATH, "rb") as f:
            raw = f.read()
        # 完整性校验: 仅当 .sha256 存在时才验证
        digest_path = CONFIG_PATH + ".sha256"
        if os.path.isfile(digest_path):
            try:
                expected = open(digest_path, "r", encoding="ascii").read().strip()
            except OSError:
                expected = ""
            actual = _sha256_of_bytes(raw)
            if expected != actual:
                # 校验失败 → 配置可能被篡改, 丢弃
                return cfg
        saved = json.loads(raw.decode("utf-8"))
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    """保存配置, 原子写入 + SHA-256 校验和。

    先写 config.json.tmp → 计算 SHA-256 → 写 config.json.sha256 → os.replace 覆盖
    保证即使中途崩溃也不会留下半写文件。
    """
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        content = json.dumps(cfg, ensure_ascii=False, indent=2)
        raw = content.encode("utf-8")
        tmp_path = CONFIG_PATH + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(raw)
        # 生成校验和
        digest = _sha256_of_bytes(raw)
        digest_path = CONFIG_PATH + ".sha256"
        with open(digest_path, "w", encoding="ascii") as f:
            f.write(digest)
        # 原子替换 (Windows / POSIX 均支持)
        os.replace(tmp_path, CONFIG_PATH)
    except OSError:
        # 清理残留临时文件
        try:
            if os.path.isfile(CONFIG_PATH + ".tmp"):
                os.remove(CONFIG_PATH + ".tmp")
        except OSError:
            pass

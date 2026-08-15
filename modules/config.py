# -*- coding: utf-8 -*-
"""配置的保存与加载(JSON), 存放在用户目录 ~/.nuitka_gui/config.json。"""

import json
import os

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nuitka_gui")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

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
}


def load_config():
    """读取配置, 失败时返回默认配置。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in cfg})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    """保存配置, 失败时静默忽略。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

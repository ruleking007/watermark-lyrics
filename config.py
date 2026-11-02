# -*- coding: utf-8 -*-
"""配置持久化 + 全局样式常量"""
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get("APPDATA", str(Path.home()))) / "WatermarkLyric"
ROOT.mkdir(parents=True, exist_ok=True)
FILE = ROOT / "config.json"

DEFAULTS = {
    "enabled": True,
    "opacity": 58,       # 水印整体不透明度 0-100
    "font_size": 21,     # 正文字号 px
    "line_count": 5,     # 可见歌词行数
    "karaoke": True,     # 已唱部分着色
    "karaoke_color": "accent",  # accent=网易云红, main=同主色
    "corner": "br",      # tl / tr / bl / br
    "margin": 36,        # 距屏幕边缘
    "ink": None,         # None=自动判定, white / dark （浅色壁纸用深色字）
    "show_meta": True,   # 是否显示"歌名 · 歌手"小字行
    "edge_dx": None,     # 到贴边的距离，随宽度变化保持贴边
    "edge_dy": None,
    "pos_x": None,       # 旧版绝对坐标，只用于迁移
    "pos_y": None,
    "panel_x": None,
    "panel_y": None,
    "collapsed": False,
}

ACCENT = "#EC4141"       # 网易云红
TEXT = "#1B1C1F"
TEXT_SUB = "#8A8F98"
BORDER = "#E9EBEF"


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            data = json.loads(FILE.read_text("utf-8"))
            if isinstance(data, dict):
                self.update({k: v for k, v in data.items() if k in DEFAULTS})
        except Exception:
            pass

    def save(self):
        try:
            FILE.write_text(json.dumps(self, ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass

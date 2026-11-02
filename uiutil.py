# -*- coding: utf-8 -*-
"""界面公共小工具"""
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPixmap

from config import ACCENT


def ui_font():
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is None:
        return "Microsoft YaHei UI"
    db = QFontDatabase()
    families = set(db.families())
    for fam in ("Microsoft YaHei UI", "Microsoft YaHei", "微软雅黑", "Segoe UI"):
        if fam in families:
            return fam
    return "Segoe UI"


def make_icon(size=32):
    """托盘/标题图标：圆角方块 + 三行歌词"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.5, 0.5, size - 1, size - 1, size * 0.28, size * 0.28)
    p.fillPath(path, QColor(ACCENT))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 235))
    w = [0.52, 0.36, 0.44]
    y = size * 0.30
    for i in range(3):
        p.drawRoundedRect(QRect(int(size * 0.24), int(y), int(size * w[i]), max(2, int(size * 0.075))),
                          size * 0.04, size * 0.04)
        y += size * 0.16
    p.end()
    return QIcon(pm)

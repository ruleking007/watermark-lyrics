# -*- coding: utf-8 -*-
"""歌词缓存工坊：搜歌 → 预览候选 → 逐句精准对时 → 回写 / 匹配给正在播放的歌曲

两种打开方式：
  * 水印面板「歌词编辑」/ 托盘菜单：连接播放器，可读实时进度，并可一键把
    选中的歌词文件匹配给正在播放的那首歌；
  * 直接运行本文件：离线编辑器，适合把几个候选版本预览给客户挑选。
"""
import copy
import os
import sys
import time
from pathlib import Path

from PyQt5.QtCore import QItemSelectionModel, QPointF, QRectF, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter,
                         QPainterPath, QPen, QRadialGradient)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
                             QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QShortcut,
                             QSizePolicy, QSplitter, QStyle, QStyledItemDelegate, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

import lyriclib as ll
from config import ACCENT, BORDER, TEXT, TEXT_SUB
from uiutil import make_icon, ui_font

MONO = "Consolas"

QSS = f"""
QWidget#root {{ background: #F1F2F5; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QLabel#h1 {{ font-size: 15px; font-weight: 600; }}
QLabel#sub {{ font-size: 11px; color: {TEXT_SUB}; }}
QLabel#path {{ font-size: 11px; color: #A6ABB3; }}
QLabel#tip {{ font-size: 10px; color: #A6ABB3; }}
QLabel#tag {{ font-size: 10px; color: {TEXT_SUB}; background: #F1F2F5;
              border-radius: 5px; padding: 1px 6px; }}
QLabel#dirty {{ font-size: 11px; color: {ACCENT}; font-weight: 600; }}
QLabel#clock {{ font-family: "{MONO}"; font-size: 26px; font-weight: 600; color: {TEXT}; }}

QFrame#card {{ background: #FFFFFF; border: 1px solid rgba(20,22,26,0.07); border-radius: 14px; }}

QPushButton {{ border: none; border-radius: 8px; padding: 5px 10px; font-size: 11px; }}
QPushButton#soft {{ background: #F3F4F7; color: {TEXT}; }}
QPushButton#soft:hover {{ background: #E9EBEF; }}
QPushButton#soft:disabled {{ background: #F6F7F9; color: #C6CAD1; }}
QPushButton#primary {{ background: {ACCENT}; color: #FFFFFF; font-weight: 600; }}
QPushButton#primary:hover {{ background: #D93A3A; }}
QPushButton#primary:disabled {{ background: #F2D3D3; color: #FFFFFF; }}
QPushButton#outline {{ background: #FFF1F1; color: {ACCENT}; font-weight: 600;
                       border: 1px solid #F6C9C9; }}
QPushButton#outline:hover {{ background: #FFE6E6; }}
QPushButton#outline:disabled {{ color: #D9B5B5; background: #FAF4F4; border-color: #F0E0E0; }}
QPushButton#chip {{ background: #F3F4F7; color: {TEXT_SUB}; font-size: 11px; padding: 3px 9px;
                    border-radius: 7px; }}
QPushButton#chip:hover {{ background: #E9EBEF; }}
QPushButton#chip:checked {{ background: #FFECEC; color: {ACCENT}; font-weight: 600; }}

QLineEdit#search {{ border: 1px solid #E4E6EB; border-radius: 10px; padding: 6px 12px;
                    font-size: 12px; background: #FFFFFF; }}
QLineEdit#search:focus {{ border-color: {ACCENT}; }}

QListWidget#results {{ border: none; background: transparent; outline: none; }}
QListWidget#results::item {{ border: none; }}

QTableWidget {{ border: none; background: #FFFFFF; gridline-color: #F3F4F7;
                font-size: 12px; selection-background-color: #FFE9E9;
                selection-color: {TEXT}; }}
QTableWidget::item {{ border-bottom: 1px solid #F5F6F8; }}
QHeaderView::section {{ background: #FAFBFC; color: {TEXT_SUB}; font-size: 10px;
                        border: none; border-bottom: 1px solid #EDEFF3; padding: 5px 6px; }}
QScrollBar:vertical {{ width: 9px; background: transparent; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #D9DDE3; border-radius: 4px; min-height: 26px; }}
QScrollBar::handle:vertical:hover {{ background: #C6CBD3; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QCheckBox {{ font-size: 11px; color: {TEXT_SUB}; spacing: 6px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border: 1px solid #D5D9DF;
                        border-radius: 4px; background: #FFFFFF; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSplitter::handle {{ background: transparent; }}
"""


def _elide(text, font, width):
    return QFontMetrics(font).elidedText(text, Qt.ElideRight, max(10, int(width)))


class ResultDelegate(QStyledItemDelegate):
    """候选列表：歌名 + 元数据 + 命中度"""

    def sizeHint(self, option, index):
        return QSize(220, 56)

    def paint(self, painter, option, index):
        rec = index.data(Qt.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect).adjusted(3, 2, -3, -2)
        if rec is None:
            painter.setPen(QColor("#A6ABB3"))
            f = QFont(painter.font()); f.setPixelSize(11)
            painter.setFont(f)
            painter.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignLeft | Qt.AlignVCenter,
                             index.data(Qt.DisplayRole) or "")
            painter.restore()
            return
        path = QPainterPath(); path.addRoundedRect(r, 10, 10)
        if option.state & QStyle.State_Selected:
            painter.fillPath(path, QColor("#FFEAEA"))
            painter.setPen(QPen(QColor(236, 65, 65, 60), 1)); painter.drawPath(path)
        elif option.state & QStyle.State_MouseOver:
            painter.fillPath(path, QColor("#F5F6F8"))

        fam = ui_font()
        f1 = QFont(fam); f1.setPixelSize(13); f1.setWeight(QFont.DemiBold)
        f2 = QFont(fam); f2.setPixelSize(10)
        fm1, fm2 = QFontMetrics(f1), QFontMetrics(f2)
        badge = 44 if rec.score else 0
        left = r.left() + 11
        avail = r.width() - 22 - badge
        title = ("★ " if rec.current else "") + (rec.disp_title or rec.path.stem)
        painter.setFont(f1)
        painter.setPen(QColor(ACCENT if option.state & QStyle.State_Selected else TEXT))
        painter.drawText(QRectF(left, r.top() + 8, avail, 17), Qt.AlignLeft | Qt.AlignVCenter,
                         fm1.elidedText(title, Qt.ElideRight, int(avail)))
        sub = "%s · %s · %d 句 · %s" % (rec.disp_artist or "未知歌手", rec.source_label,
                                        rec.count, ll.fmt_time(rec.end_time))
        painter.setFont(f2)
        painter.setPen(QColor(TEXT_SUB))
        painter.drawText(QRectF(left, r.top() + 28, r.width() - 22, 15),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         fm2.elidedText(sub, Qt.ElideRight, int(r.width() - 22)))
        if rec.score:
            painter.setPen(QColor(ACCENT if rec.score >= 0.9 else TEXT_SUB))
            painter.drawText(QRectF(r.right() - 56, r.top() + 8, 46, 17),
                             Qt.AlignRight | Qt.AlignVCenter, "%d%%" % round(rec.score * 100))
        painter.restore()


class WatermarkPreview(QWidget):
    """按水印样式预览：当前句居中，上下文渐隐，右下角歌名"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.lines = []
        self.center = 0
        self.title = ""
        self.artist = ""
        self.ink = "white"
        self.prog = 1.0
        self.rows = 5
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, lines, center=0, title="", artist="", ink=None):
        self.lines = lines or []
        n = len(self.lines)
        self.center = max(0, min(int(center), n - 1)) if n else 0
        self.title, self.artist = title, artist
        if ink:
            self.ink = ink
        self.update()

    def set_center(self, i):
        n = len(self.lines)
        if not n:
            return
        i = max(0, min(int(i), n - 1))
        if i != self.center:
            self.center = i
            self.update()

    def set_prog(self, p):
        p = max(0.0, min(1.0, float(p)))
        if abs(p - self.prog) > 0.004:
            self.prog = p
            self.update()

    # ---------------------------------------------------------- 绘制
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if r.width() < 4 or r.height() < 4:
            return
        clip = QPainterPath(); clip.addRoundedRect(r, 13, 13)
        p.save(); p.setClipPath(clip)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        if self.ink == "white":
            g.setColorAt(0.0, QColor("#2C333E")); g.setColorAt(0.55, QColor("#1B2027"))
            g.setColorAt(1.0, QColor("#0F1318"))
        else:
            g.setColorAt(0.0, QColor("#F7F5F1")); g.setColorAt(0.6, QColor("#EDEAE4"))
            g.setColorAt(1.0, QColor("#DEDAD2"))
        p.fillRect(self.rect(), g)
        for cx, cy, rad, alpha in ((0.80, 0.18, 0.62, 26), (0.14, 0.90, 0.58, 16)):
            rg = QRadialGradient(QPointF(r.width() * cx, r.height() * cy),
                                 min(r.width(), r.height()) * rad)
            rg.setColorAt(0.0, QColor(255, 255, 255, alpha))
            rg.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), rg)
        pen = QPen(QColor(255, 255, 255, 26) if self.ink == "white" else QColor(0, 0, 0, 16), 1)
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawPath(clip)
        p.restore()

        # 角标
        f = QFont(ui_font()); f.setPixelSize(10)
        p.setFont(f)
        tag = "水印预览"
        if self.lines:
            tag += " · 第 %d / %d 句 · %s" % (self.center + 1, len(self.lines),
                                              ll.fmt_time(self.lines[self.center][0]))
        p.setPen(QColor(255, 255, 255, 120) if self.ink == "white" else QColor(0, 0, 0, 90))
        p.drawText(QRectF(r.left() + 14, r.top() + 10, r.width() - 28, 16),
                   Qt.AlignLeft | Qt.AlignVCenter, tag)

        if not self.lines:
            f = QFont(ui_font()); f.setPixelSize(13)
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 150) if self.ink == "white" else QColor(0, 0, 0, 120))
            p.drawText(r, Qt.AlignCenter, "在左侧选择一个歌词文件，这里即时预览水印效果")
            return

        meta_h = 22
        base = max(12, min(30, int((r.height() - meta_h - 18) / (self.rows * 1.62))))
        lh = base * 1.62
        mid = r.top() + (r.height() - meta_h) / 2.0
        half = (self.rows - 1) / 2.0
        for d in range(-int(half), int(half) + 1):
            i = self.center + d
            if i < 0 or i >= len(self.lines):
                continue
            a = 1.0 if d == 0 else 0.40 ** abs(d)
            size = base if d == 0 else base * (1.0 - 0.05 * min(abs(d), 1.6))
            self._line(p, self.lines[i][1], size, mid + d * lh, r.width(), a,
                       d == 0 and self.prog < 0.999)
        # 歌名
        meta = self.title or self.lines[self.center][1][:6]
        if self.artist:
            meta += " · " + self.artist
        f = QFont(ui_font()); f.setPixelSize(max(9, int(base * 0.58)))
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 150) if self.ink == "white" else QColor(0, 0, 0, 110))
        p.drawText(QRectF(r.left() + 16, r.bottom() - meta_h - 2, r.width() - 32, meta_h),
                   Qt.AlignRight | Qt.AlignVCenter, _elide(meta, f, r.width() - 32))

    def _line(self, p, text, size, cy, width, alpha, karaoke):
        if not text:
            return
        f = QFont(ui_font())
        f.setPixelSize(max(9, int(round(size))))
        f.setWeight(QFont.DemiBold if alpha > 0.9 else QFont.Normal)
        fm = QFontMetrics(f)
        p.setFont(f)
        rect = QRectF(20, cy - size * 0.85, width - 40, size * 1.7)
        t = fm.elidedText(text, Qt.ElideRight, int(rect.width()))
        white = self.ink == "white"
        main = QColor(255, 255, 255) if white else QColor(28, 30, 34)
        halo = QColor(0, 0, 0, 70) if white else QColor(255, 255, 255, 120)
        p.setPen(halo)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.setOpacity(alpha * 0.5)
            p.drawText(rect.translated(dx, dy), Qt.AlignRight | Qt.AlignVCenter, t)
        p.setOpacity(alpha)
        sung = QColor(255, 90, 95) if white else QColor(236, 65, 65)
        if not karaoke:
            p.setPen(main)
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, t)
        else:
            p.setPen(QColor(main.red(), main.green(), main.blue(), 165))
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, t)
            tw = fm.horizontalAdvance(t)
            x0 = rect.right() - tw
            p.save(); p.setClipRect(QRectF(x0, rect.top() - 3, tw * self.prog, rect.height() + 6))
            p.setPen(sung)
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, t)
            p.restore()
        p.setOpacity(1.0)


class LyricEditor(QWidget):
    """歌词缓存编辑器主窗口"""

    def __init__(self, app=None, folder=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.app = app
        self.lib = ll.Library(folder)
        self.rec = None
        self.lines = []
        self.meta = {}
        self.dirty = False
        self._undo = []
        self._redo = []
        self._loading = False
        self._loading_list = False
        self._results = []
        self._step = 0.1
        self._scope = "line"
        self._play_idx = -1
        self._demo_pos = 0.0
        self._demo_on = False
        self._demo = False
        self._geo_backup = None
        self._synced_key = None
        self._last_mono = time.monotonic()

        self.setObjectName("root")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowTitle("歌词缓存工坊")
        self.setWindowIcon(make_icon(64))
        self.resize(1180, 860)
        self.setMinimumSize(980, 660)
        self.setStyleSheet(QSS)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._run_search)

        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._default_hint)

        self._build()
        self._shortcuts()
        self._update_stats()
        self._run_search()
        self.sync_track()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(80)
        self._clock_timer.timeout.connect(self._on_tick)
        self._clock_timer.start()

    # ================================================================ 界面
    def _btn(self, text, kind="soft"):
        b = QPushButton(text)
        b.setObjectName({"accent": "primary", "outline": "outline"}.get(kind, "soft"))
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _chip(self, text, checked=False):
        b = QPushButton(text)
        b.setObjectName("chip"); b.setCheckable(True); b.setChecked(checked)
        b.setCursor(Qt.PointingHandCursor); b.setFixedHeight(24)
        return b

    @staticmethod
    def _tag(text):
        l = QLabel(text)
        l.setObjectName("tag"); l.setAlignment(Qt.AlignCenter)
        return l

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.setSpacing(10)

        # ---- 顶栏
        self.topbar = QWidget()
        top = QHBoxLayout(self.topbar)
        top.setContentsMargins(0, 0, 0, 0); top.setSpacing(10)
        dot = QLabel(); dot.setFixedSize(8, 8)
        dot.setStyleSheet("background:%s;border-radius:4px;" % ACCENT)
        col = QVBoxLayout(); col.setSpacing(1)
        self.lbl_app = QLabel("歌词缓存工坊"); self.lbl_app.setObjectName("h1")
        self.lbl_stat = QLabel(""); self.lbl_stat.setObjectName("sub")
        self.lbl_stat.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(self.lbl_app); col.addWidget(self.lbl_stat)
        top.addWidget(dot, 0, Qt.AlignTop); top.addLayout(col); top.addStretch(1)
        self.search = QLineEdit(); self.search.setObjectName("search")
        self.search.setPlaceholderText("输入歌名 / 歌手 / 歌词片段…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(320); self.search.setFixedHeight(34)
        self.search.textChanged.connect(lambda *_: self._search_timer.start())
        self.search.returnPressed.connect(self._run_search)
        self.btn_reload = self._btn("刷新索引"); self.btn_reload.clicked.connect(self._on_reload)
        self.btn_folder = self._btn("打开文件夹"); self.btn_folder.clicked.connect(self._open_folder)
        top.addWidget(self.search, 0, Qt.AlignVCenter)
        top.addWidget(self.btn_reload, 0, Qt.AlignVCenter)
        top.addWidget(self.btn_folder, 0, Qt.AlignVCenter)
        root.addWidget(self.topbar)

        # ---- 主体
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(12)
        self.left = self._build_left()
        self.right = self._build_right()
        self.split.addWidget(self.left); self.split.addWidget(self.right)
        self.split.setStretchFactor(0, 0); self.split.setStretchFactor(1, 1)
        self.split.setSizes([340, 840])
        root.addWidget(self.split, 1)

        # ---- 状态栏
        self.statusbar = QWidget()
        st = QHBoxLayout(self.statusbar)
        st.setContentsMargins(2, 0, 2, 0); st.setSpacing(10)
        self.lbl_hint = QLabel(""); self.lbl_hint.setObjectName("sub")
        self.lbl_dirty = QLabel(""); self.lbl_dirty.setObjectName("dirty")
        st.addWidget(self.lbl_hint, 1); st.addWidget(self.lbl_dirty)
        root.addWidget(self.statusbar)
        self._default_hint()

        self._demo_hide = [self.topbar, self.left, self.timeline_card, self.statusbar]

    def _build_left(self):
        card = QFrame(); card.setObjectName("card")
        card.setMinimumWidth(300); card.setMaximumWidth(430)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(8)

        now = QHBoxLayout(); now.setSpacing(6)
        self.lbl_now = QLabel("离线模式")
        self.lbl_now.setObjectName("sub")
        self.lbl_now.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_now = self._btn("搜这首歌")
        self.btn_now.clicked.connect(self._search_now_playing)
        now.addWidget(self.lbl_now, 1); now.addWidget(self.btn_now)
        lay.addLayout(now)

        self.lbl_cand = QLabel("候选 0 个"); self.lbl_cand.setObjectName("sub")
        lay.addWidget(self.lbl_cand)

        self.list = QListWidget()
        self.list.setObjectName("results")
        self.list.setMouseTracking(True)
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setItemDelegate(ResultDelegate(self.list))
        self.list.currentItemChanged.connect(self._on_pick)
        lay.addWidget(self.list, 1)

        tip = QLabel("↑ ↓ 切换候选预览 · 双击时间或歌词直接改 · 选中后 [ ] 逐句微调")
        tip.setObjectName("tip"); tip.setWordWrap(True)
        lay.addWidget(tip)
        return card

    def _build_right(self):
        v = QSplitter(Qt.Vertical)
        v.setChildrenCollapsible(False)
        v.setHandleWidth(12)
        v.addWidget(self._build_timeline())
        v.addWidget(self._build_preview())
        v.setStretchFactor(0, 3); v.setStretchFactor(1, 2)
        v.setSizes([560, 250])
        return v

    def _build_timeline(self):
        card = QFrame(); card.setObjectName("card")
        self.timeline_card = card
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12); lay.setSpacing(8)

        head = QHBoxLayout(); head.setSpacing(6)
        hcol = QVBoxLayout(); hcol.setSpacing(1)
        self.lbl_title = QLabel("未选择歌词文件"); self.lbl_title.setObjectName("h1")
        self.lbl_meta = QLabel("在左侧挑一个候选，这里显示整首歌的逐句时间轴")
        self.lbl_meta.setObjectName("sub")
        hcol.addWidget(self.lbl_title); hcol.addWidget(self.lbl_meta)
        head.addLayout(hcol, 1)
        self.btn_as = self._btn("另存为"); self.btn_as.clicked.connect(self._save_as)
        self.btn_del = self._btn("删除"); self.btn_del.clicked.connect(self._delete)
        self.btn_apply = self._btn("匹配给正在播放", "outline")
        self.btn_apply.clicked.connect(self._apply_to_current)
        self.btn_save = self._btn("保存", "accent"); self.btn_save.clicked.connect(self.save)
        for b in (self.btn_as, self.btn_del, self.btn_apply, self.btn_save):
            head.addWidget(b, 0, Qt.AlignTop)
        lay.addLayout(head)

        self.lbl_file = QLabel(""); self.lbl_file.setObjectName("path")
        self.lbl_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_file)

        # 工具条一：逐句微调
        bar1 = QHBoxLayout(); bar1.setSpacing(4)
        bar1.addWidget(self._tag("步长"))
        self._step_group = QButtonGroup(self)
        for v_ in (0.02, 0.05, 0.1, 0.2, 0.5, 1.0):
            b = self._chip("%gs" % v_, abs(v_ - self._step) < 1e-9)
            b.setProperty("value", v_)
            self._step_group.addButton(b)
            b.clicked.connect(self._on_step)
            bar1.addWidget(b)
        bar1.addSpacing(8)
        bar1.addWidget(self._tag("作用于"))
        self._scope_group = QButtonGroup(self)
        for key, text in (("line", "仅本行"), ("from", "本行及后"), ("all", "全部")):
            b = self._chip(text, key == self._scope)
            b.setProperty("value", key)
            self._scope_group.addButton(b)
            b.clicked.connect(self._on_scope)
            bar1.addWidget(b)
        bar1.addStretch(1)
        self.btn_back = self._btn("−0.10s"); self.btn_fwd = self._btn("+0.10s")
        self.btn_back.clicked.connect(lambda: self.nudge(-self._step))
        self.btn_fwd.clicked.connect(lambda: self.nudge(self._step))
        bar1.addWidget(self.btn_back); bar1.addWidget(self.btn_fwd)
        lay.addLayout(bar1)

        # 工具条二：打点 / 撤销 / 排序 / 偏移
        bar2 = QHBoxLayout(); bar2.setSpacing(4)
        self.btn_beat = self._btn("设为当前时间 T", "accent")
        self.btn_beat.clicked.connect(self.beat)
        self.btn_undo = self._btn("撤销"); self.btn_undo.clicked.connect(self.undo)
        self.btn_redo = self._btn("重做"); self.btn_redo.clicked.connect(self.redo)
        self.btn_sort = self._btn("按时间排序"); self.btn_sort.clicked.connect(self.sort_by_time)
        self.btn_offset = self._btn("偏移清零"); self.btn_offset.clicked.connect(self.clear_offset)
        self.lbl_offset = QLabel("偏移 +0.00s"); self.lbl_offset.setObjectName("sub")
        for b in (self.btn_beat, self.btn_undo, self.btn_redo, self.btn_sort):
            bar2.addWidget(b)
        bar2.addSpacing(8); bar2.addWidget(self.lbl_offset); bar2.addWidget(self.btn_offset)
        bar2.addStretch(1)
        lay.addLayout(bar2)

        # 表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "时间", "间隔", "歌词"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(27)
        self.table.setShowGrid(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.SelectedClicked)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        for i, w in ((0, 38), (1, 84), (2, 62)):
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
            self.table.setColumnWidth(i, w)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_table_select)
        self.table.cellClicked.connect(self._on_cell_clicked)
        lay.addWidget(self.table, 1)
        return card

    def _build_preview(self):
        card = QFrame(); card.setObjectName("card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 12, 12, 12); lay.setSpacing(12)
        self.preview = WatermarkPreview()
        lay.addWidget(self.preview, 1)

        side = QVBoxLayout(); side.setSpacing(6)
        self.lbl_clock = QLabel("00:00.00"); self.lbl_clock.setObjectName("clock")
        self.lbl_state = QLabel("未播放"); self.lbl_state.setObjectName("sub")
        side.addWidget(self.lbl_clock); side.addWidget(self.lbl_state)

        row = QHBoxLayout(); row.setSpacing(6)
        self.btn_play = self._btn("▶ 预览播放", "accent")
        self.btn_play.clicked.connect(self._toggle_preview)
        self.btn_rewind = self._btn("回到开头"); self.btn_rewind.clicked.connect(self._rewind)
        row.addWidget(self.btn_play); row.addWidget(self.btn_rewind)
        side.addLayout(row)

        self.chk_follow = QCheckBox("跟随播放器进度"); self.chk_follow.setChecked(self.app is not None)
        self.chk_advance = QCheckBox("打点后跳下一句"); self.chk_advance.setChecked(True)
        self.chk_scroll = QCheckBox("预览时自动滚动"); self.chk_scroll.setChecked(True)
        for c in (self.chk_follow, self.chk_advance, self.chk_scroll):
            side.addWidget(c)

        inkrow = QHBoxLayout(); inkrow.setSpacing(4)
        inkrow.addWidget(self._tag("配色"))
        self._ink_group = QButtonGroup(self)
        for key, text in (("white", "白字"), ("dark", "黑字")):
            b = self._chip(text, key == "white")
            b.setProperty("value", key)
            self._ink_group.addButton(b)
            b.clicked.connect(self._on_ink)
            inkrow.addWidget(b)
        inkrow.addStretch(1)
        side.addLayout(inkrow)

        self.btn_demo = self._btn("大屏预览"); self.btn_demo.clicked.connect(lambda: self.toggle_demo(True))
        self.btn_exit = self._btn("退出预览 (Esc)", "accent")
        self.btn_exit.clicked.connect(lambda: self.toggle_demo(False)); self.btn_exit.hide()
        row2 = QHBoxLayout(); row2.setSpacing(6)
        row2.addWidget(self.btn_demo); row2.addWidget(self.btn_exit)
        side.addLayout(row2)

        tip = QLabel("T 打点 · [ ] 逐句微调 · Ctrl+S 保存")
        tip.setObjectName("tip"); tip.setWordWrap(True)
        side.addWidget(tip)
        side.addStretch(1)

        wrap = QWidget(); wrap.setLayout(side); wrap.setFixedWidth(184)
        lay.addWidget(wrap)
        return card

    # ================================================================ 快捷键
    def _shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)
            return s

        sc("Ctrl+S", self.save)
        sc("Ctrl+Z", self._undo_shortcut)
        sc("Ctrl+Y", self.redo)
        sc("Ctrl+Shift+Z", self.redo)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("[", lambda: self.nudge(-self._step))
        sc("]", lambda: self.nudge(self._step))
        sc("Alt+Left", lambda: self.nudge(-self._step))
        sc("Alt+Right", lambda: self.nudge(self._step))
        sc("T", self.beat)
        sc("Esc", lambda: self.toggle_demo(False) if self._demo else None)

    def _undo_shortcut(self):
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.undo()
            return
        self.undo()

    # ================================================================ 索引 / 搜索
    def _update_stats(self):
        bits = ["%d 个缓存文件" % len(self.lib.items), "%d 句" % self.lib.total_lines]
        if self.lib.bad_files:
            bits.append("%d 个文件无法解析" % len(self.lib.bad_files))
        self.lbl_stat.setText(" · ".join(bits) + "   " + str(self.lib.folder))
        self.lbl_stat.setToolTip(str(self.lib.folder))

    def _on_reload(self):
        n = self.lib.reload()
        self._update_stats()
        self._run_search()
        self._hint("已重新索引：%d 个歌词文件" % n)

    def _open_folder(self):
        path = str(self.lib.folder)
        try:
            os.startfile(path)
        except Exception:
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _run_search(self):
        self._search_timer.stop()
        q = self.search.text().strip()
        title, artist = self.current_track()
        self._results = self.lib.search(q, title, artist)
        n = len(self.lib.items)
        self.lbl_cand.setText(("候选 %d 个 / 共 %d 个缓存文件" % (len(self._results), n)) if q
                              else ("共 %d 个缓存文件，按更新时间排列" % n))
        self._fill_results()
        self._update_buttons()

    def _fill_results(self):
        self._loading_list = True
        keep = self.rec.path if self.rec else None
        self.list.clear()
        if not self._results:
            it = QListWidgetItem("没有找到匹配的歌词文件，\n换个关键词或点『刷新索引』")
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(220, 58))
            self.list.addItem(it)
        else:
            for rec in self._results:
                it = QListWidgetItem()
                it.setData(Qt.UserRole, rec)
                it.setSizeHint(QSize(220, 56))
                first = " / ".join(s for _, s in rec.lines[:2])
                it.setToolTip("%s\n%s\n%s" % (rec.path.name, rec.stamp, first))
                self.list.addItem(it)
        self._loading_list = False
        if keep:
            for i in range(self.list.count()):
                rec = self.list.item(i).data(Qt.UserRole)
                if rec is not None and rec.path == keep:
                    self.list.setCurrentRow(i)
                    return
        if self._results and self.rec is None and not self.dirty:
            self.list.setCurrentRow(0)

    def _on_pick(self, cur, _prev=None):
        if self._loading_list or cur is None:
            return
        rec = cur.data(Qt.UserRole)
        if rec is None:
            return
        if self.rec is not None and rec.path == self.rec.path:
            return
        if not self._guard():
            self._loading_list = True
            if self.rec is not None:
                for i in range(self.list.count()):
                    r = self.list.item(i).data(Qt.UserRole)
                    if r is not None and r.path == self.rec.path:
                        self.list.setCurrentRow(i)
                        break
            self._loading_list = False
            return
        self.load_record(rec)

    # ================================================================ 载入 / 展示
    def current_track(self):
        if self.app is None:
            return "", ""
        key = getattr(self.app, "_key", None)
        if key and key[0]:
            return key[0], (key[1] or "")
        return "", ""

    def sync_track(self):
        """由水印程序在切歌时调用；只有歌曲真的变了才重新搜索"""
        title, artist = self.current_track()
        if self.app is None:
            self.lbl_now.setText("离线模式 · 未连接播放器")
            self.btn_now.setEnabled(False)
            self.chk_follow.setVisible(False)
        else:
            self.lbl_now.setText(("正在播放  %s · %s" % (title, artist)) if title else "当前没有在播放的歌曲")
            self.btn_now.setEnabled(bool(title))
        key = (title, artist)
        if key == self._synced_key:
            self._update_buttons()
            return
        self._synced_key = key
        if not title or self.app is None:
            self._update_buttons()
            return
        if self.dirty:
            self._hint("当前文件有未保存的修改，未自动切换到《%s》" % title)
            self._update_buttons()
            return
        self.search.setText(title)
        self._run_search()
        target = self.lib.target_path(title, artist)
        for i in range(self.list.count()):
            rec = self.list.item(i).data(Qt.UserRole)
            if rec is not None and rec.path == target:
                self.list.setCurrentRow(i)
                break
        self._update_buttons()

    def _search_now_playing(self):
        title, _artist = self.current_track()
        if not title:
            self._hint("当前没有在播放的歌曲")
            return
        self.search.setText(title)
        self._run_search()

    def load_record(self, rec):
        self.rec = rec
        self.lines = [[round(float(t), 2), s] for t, s in rec.lines]
        self.meta = {k: v for k, v in rec.data.items() if k != "lines"}
        self.dirty = False
        self._undo.clear(); self._redo.clear()
        self._demo_pos = 0.0; self._demo_on = False
        self._play_idx = -1
        self._fill_table()
        self._render_header()
        self._update_buttons()
        self.preview.set_data(self.lines, self.table.currentRow() if self.table.currentRow() >= 0 else 0,
                              rec.disp_title, rec.disp_artist, self._ink())
        self.preview.set_prog(1.0)
        self._hint("已载入 %s · 双击时间或歌词即可修改" % rec.path.name)

    def _ink(self):
        for b in self._ink_group.buttons():
            if b.isChecked():
                return b.property("value")
        return "white"

    def _render_header(self):
        if self.rec is None:
            self.lbl_title.setText("未选择歌词文件")
            self.lbl_meta.setText("在左侧挑一个候选，这里显示整首歌的逐句时间轴")
            self.lbl_file.setText("")
            self.lbl_offset.setText("偏移 +0.00s")
            return
        rec = self.rec
        self.lbl_title.setText(rec.disp_title or rec.path.stem)
        bits = [rec.disp_artist or "未知歌手", rec.source_label, "%d 句" % len(self.lines),
                "首句 " + ll.fmt_time(self.lines[0][0]) if self.lines else "",
                "末句 " + ll.fmt_time(self.lines[-1][0]) if self.lines else ""]
        if rec.duration:
            bits.append("歌曲时长 " + ll.fmt_time(rec.duration))
        if not ll.is_sorted(self.lines):
            bits.append("⚠ 时间未按顺序")
        self.lbl_meta.setText("  ·  ".join(b for b in bits if b))
        self.lbl_file.setText(rec.path.name + "    " + str(rec.path))
        self.lbl_file.setToolTip(str(rec.path))
        off = float(self.meta.get("offset") or 0.0)
        self.lbl_offset.setText("偏移 %+.2f s" % off)
        self.btn_offset.setEnabled(abs(off) > 0.005)
        self.setWindowTitle("歌词缓存工坊 · %s" % (rec.disp_title or rec.path.stem))

    def _fill_table(self, keep_row=None):
        self._loading = True
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(self.lines))
        mono = QFont(MONO); mono.setStyleHint(QFont.Monospace); mono.setPixelSize(12)
        small = QFont(ui_font()); small.setPixelSize(11)
        for i, (t, s) in enumerate(self.lines):
            it0 = QTableWidgetItem(str(i + 1))
            it0.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it0.setTextAlignment(Qt.AlignCenter); it0.setForeground(QColor("#B4B9C1"))
            it0.setFont(small)
            it1 = QTableWidgetItem(ll.fmt_time(t))
            it1.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter); it1.setFont(mono)
            it1.setToolTip("双击修改，可输入 01:23.45 或 83.45")
            it2 = QTableWidgetItem(ll.gap_text(self.lines, i))
            it2.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it2.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter); it2.setFont(mono)
            it2.setForeground(QColor(TEXT_SUB))
            if i:
                it2.setToolTip("与上一句的间隔")
            it3 = QTableWidgetItem(s)
            it3.setToolTip(s)
            for c, it in enumerate((it0, it1, it2, it3)):
                self.table.setItem(i, c, it)
        self.table.setUpdatesEnabled(True)
        self._loading = False
        self._refresh_row_styles()
        row = keep_row if keep_row is not None else (len(self.lines) - 1 if self.lines else -1)
        if keep_row is None:
            row = 0 if self.lines else -1
        if row >= 0:
            self.table.setCurrentCell(min(row, len(self.lines) - 1), 3)
        self._on_table_select()

    def _refresh_time_cells(self):
        self._loading = True
        for i, (t, _s) in enumerate(self.lines):
            self.table.item(i, 1).setText(ll.fmt_time(t))
            gap = ll.gap_text(self.lines, i)
            self.table.item(i, 2).setText(gap)
            self.table.item(i, 2).setForeground(
                QColor("#D93025") if (i and gap.startswith("-")) else QColor(TEXT_SUB))
        self._loading = False

    def _refresh_row_styles(self):
        for i in range(len(self.lines)):
            self._set_row_style(i)

    def _set_row_style(self, i):
        if not (0 <= i < len(self.lines)):
            return
        t = self.lines[i][0]
        bad = i > 0 and t < self.lines[i - 1][0] - 1e-9
        if i == self._play_idx:
            bg = QColor("#FFEDED")
        elif bad:
            bg = QColor("#FFF7E6")
        else:
            bg = QColor("#FFFFFF") if i % 2 == 0 else QColor("#FBFBFC")
        for c in range(self.table.columnCount()):
            it = self.table.item(i, c)
            if it is None:
                continue
            it.setBackground(bg)
            if c == 1:
                it.setForeground(QColor("#D93025") if bad else QColor(TEXT))

    # ================================================================ 选中 / 预览
    def _target_rows(self):
        sel = self.table.selectionModel()
        rows = sorted({i.row() for i in sel.selectedRows()}) if sel is not None else []
        if not rows:
            r = self.table.currentRow()
            rows = [r] if r >= 0 else []
        return [r for r in rows if 0 <= r < len(self.lines)]

    def _on_table_select(self):
        rows = self._target_rows()
        if rows:
            self.preview.set_center(rows[0])
            self.preview.set_prog(1.0)

    def _on_cell_clicked(self, row, _col):
        if 0 <= row < len(self.lines):
            self.preview.set_center(row)
            self.preview.set_prog(1.0)
            if not self._follow_active():
                self._demo_pos = float(self.lines[row][0])

    # ================================================================ 编辑
    def _on_item_changed(self, item):
        if self._loading or self.rec is None:
            return
        row, col = item.row(), item.column()
        if not (0 <= row < len(self.lines)):
            return
        if col == 1:
            try:
                t = ll.parse_time(item.text())
            except ValueError:
                self._loading = True
                item.setText(ll.fmt_time(self.lines[row][0]))
                self._loading = False
                self._hint("时间格式无法识别：%s（示例：01:23.45 或 83.45）" % item.text())
                return
            if abs(t - self.lines[row][0]) < 0.005:
                self._loading = True
                item.setText(ll.fmt_time(self.lines[row][0]))
                self._loading = False
                return
            self._push_undo()
            self.lines[row][0] = t
            self._after_edit("第 %d 句时间 → %s" % (row + 1, ll.fmt_time(t)))
        elif col == 3:
            s = item.text().replace("\n", " ").strip()
            if s == self.lines[row][1]:
                return
            self._push_undo()
            self.lines[row][1] = s
            self._after_edit("第 %d 句歌词已修改" % (row + 1))

    def _after_edit(self, message=""):
        self.dirty = True
        self._refresh_time_cells()
        self._refresh_row_styles()
        self._render_header()
        self._update_buttons()
        if self.rec is not None:
            self.preview.set_data(self.lines, self.preview.center, self.rec.disp_title,
                                  self.rec.disp_artist, self._ink())
        if message:
            self._hint(message)

    def _push_undo(self):
        self._undo.append((copy.deepcopy(self.lines), copy.deepcopy(self.meta), self._target_rows()))
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            self._hint("没有可撤销的操作")
            return
        self._redo.append((copy.deepcopy(self.lines), copy.deepcopy(self.meta), self._target_rows()))
        lines, meta, rows = self._undo.pop()
        self.lines, self.meta = lines, meta
        self._restore(rows, "已撤销")

    def redo(self):
        if not self._redo:
            self._hint("没有可重做的操作")
            return
        self._undo.append((copy.deepcopy(self.lines), copy.deepcopy(self.meta), self._target_rows()))
        lines, meta, rows = self._redo.pop()
        self.lines, self.meta = lines, meta
        self._restore(rows, "已重做")

    def _restore(self, rows, message):
        self.dirty = True
        self._fill_table(keep_row=(rows[0] if rows else 0))
        self._render_header()
        self._update_buttons()
        if self.rec is not None:
            self.preview.set_data(self.lines, self.preview.center, self.rec.disp_title,
                                  self.rec.disp_artist, self._ink())
        self._hint(message)

    # ================================================================ 工具条
    def _on_step(self):
        b = self.sender()
        if b is None:
            return
        self._step = float(b.property("value"))
        self.btn_back.setText("−%.2fs" % self._step)
        self.btn_fwd.setText("+%.2fs" % self._step)
        self._hint("微调步长 %.2f 秒" % self._step)

    def _on_scope(self):
        b = self.sender()
        if b is None:
            return
        self._scope = str(b.property("value"))
        self._hint({"line": "只改选中这一句",
                    "from": "改选中句以及它后面的所有句",
                    "all": "改整首歌的每一句"}.get(self._scope, ""))

    def _on_ink(self):
        b = self.sender()
        if b is None:
            return
        ink = str(b.property("value"))
        if self.rec is not None:
            self.preview.set_data(self.lines, self.preview.center, self.rec.disp_title,
                                  self.rec.disp_artist, ink)
        else:
            self.preview.ink = ink
            self.preview.update()

    def nudge(self, delta):
        if self.rec is None or not self.lines:
            return
        rows = ll.scope_rows(self._target_rows(), len(self.lines), self._scope)
        if not rows:
            self._hint("先点一句歌词，再微调")
            return
        self._push_undo()
        self.lines = ll.shift(self.lines, rows, delta)
        self._after_edit("第 %d–%d 句 %+.2f s" % (rows[0] + 1, rows[-1] + 1, delta))

    def beat(self):
        """把选中句的时间设成当前播放/预览进度"""
        if self.rec is None or not self.lines:
            return
        fw = self.table.state()
        if fw == QAbstractItemView.EditingState:
            return
        pos, playing = self._now()
        if not playing:
            self._hint("现在没有在播放，先在网易云里放歌或点『预览播放』")
            return
        rows = self._target_rows()
        if not rows:
            self._hint("先点一句歌词，再按 T 打点")
            return
        self._push_undo()
        for r in rows:
            self.lines[r][0] = round(pos, 2)
        nxt = min(max(rows) + 1, len(self.lines) - 1)
        self.dirty = True
        self._refresh_time_cells()
        self._refresh_row_styles()
        self._render_header()
        self._update_buttons()
        if self.chk_advance.isChecked() and nxt != max(rows):
            self.table.setCurrentCell(nxt, 3)
            self.table.clearSelection()
        self._hint("第 %d 句打点为 %s" % (rows[0] + 1, ll.fmt_time(pos)))

    def sort_by_time(self):
        if not self.lines:
            return
        self._push_undo()
        self.lines = ll.sort_lines(self.lines)
        self.dirty = True
        self._fill_table(keep_row=0)
        self._render_header()
        self._update_buttons()
        self._hint("已按时间重新排序")

    def clear_offset(self):
        if not self.meta:
            return
        off = float(self.meta.get("offset") or 0.0)
        if abs(off) < 0.005:
            self._hint("这份歌词没有全局偏移")
            return
        rec = QMessageBox.question(self, "偏移清零",
                                   "把 offset %+.2f s 并入每一句的时间（每句 %+.2f s），然后清零？"
                                   % (off, -off))
        if rec != QMessageBox.Yes:
            return
        self._push_undo()
        self.lines = ll.shift(self.lines, range(len(self.lines)), -off)
        self.meta["offset"] = 0.0
        self.dirty = True
        self._fill_table(keep_row=0)
        self._render_header()
        self._update_buttons()
        self._hint("偏移已并入时间轴，offset 归零")

    # ================================================================ 播放进度
    def _follow_active(self):
        return self.app is not None and self.chk_follow.isChecked()

    def _now(self):
        if self._follow_active():
            clock = getattr(self.app, "clock", None)
            if clock is not None:
                try:
                    return max(0.0, float(clock.pos) + float(clock.offset)), bool(clock.playing)
                except Exception:
                    pass
        return self._demo_pos, self._demo_on

    def _index_at(self, pos):
        if not self.lines:
            return -1
        idx = 0
        for i, (t, _s) in enumerate(self.lines):
            if float(t) <= pos + 1e-6:
                idx = i
            else:
                break
        return idx

    def _line_prog(self, idx, pos):
        if not (0 <= idx < len(self.lines)):
            return 1.0
        t0 = float(self.lines[idx][0])
        t1 = float(self.lines[idx + 1][0]) if idx + 1 < len(self.lines) else t0 + 4.0
        if pos >= t1:
            return 1.0
        return max(0.0, min(1.0, (pos - t0) / max(0.45, t1 - t0)))

    def _on_tick(self):
        mono = time.monotonic()
        dt = mono - self._last_mono
        self._last_mono = mono
        if self._demo_on and not self._follow_active():
            self._demo_pos += min(0.5, max(0.0, dt))
            if self.lines and self._demo_pos > float(self.lines[-1][0]) + 8:
                self._demo_on = False
        pos, playing = self._now()
        self.lbl_clock.setText(ll.fmt_time(pos))
        if self._follow_active():
            self.lbl_state.setText("跟随播放器 · " + ("播放中" if playing else "已暂停"))
        else:
            self.lbl_state.setText("预览播放中" if playing else ("已暂停" if pos > 0.01 else "未播放"))
        self.btn_play.setText("❙❙ 暂停" if (self._demo_on and not self._follow_active()) else "▶ 预览播放")
        if not self.lines:
            return
        idx = self._index_at(pos)
        if idx != self._play_idx:
            old = self._play_idx
            self._play_idx = idx
            for i in (old, idx):
                self._set_row_style(i)
            if self._demo and self.chk_scroll.isChecked():
                self._scroll_to(idx)
        if self._demo:
            self.preview.set_center(idx)
            self.preview.set_prog(self._line_prog(idx, pos) if self._demo_on else 1.0)
        elif self._demo_on and not self._follow_active():
            self.preview.set_center(idx)
            self.preview.set_prog(self._line_prog(idx, pos))

    def _scroll_to(self, row):
        if 0 <= row < self.table.rowCount():
            item = self.table.item(row, 3)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

    def _toggle_preview(self):
        if not self.lines:
            self._hint("先选一个歌词文件")
            return
        if self._demo_on and not self._follow_active():
            self._demo_on = False
        else:
            if self._follow_active():
                self._hint("正在跟随播放器进度，取消勾选『跟随播放器进度』即可单独预览")
                return
            if self._demo_pos >= float(self.lines[-1][0]) + 4 or self._demo_pos <= 0.01:
                self._demo_pos = float(self.lines[0][0])
            self._demo_on = True
        self._last_mono = time.monotonic()
        self._on_tick()

    def _rewind(self):
        self._demo_pos = float(self.lines[0][0]) if self.lines else 0.0
        self._play_idx = -1
        self._on_tick()

    # ================================================================ 大屏预览
    def toggle_demo(self, on=None):
        on = (not self._demo) if on is None else bool(on)
        if on == self._demo:
            return
        self._demo = on
        for w in self._demo_hide:
            w.setVisible(not on)
        self.btn_demo.setVisible(not on)
        self.btn_exit.setVisible(on)
        self.chk_follow.setVisible((not on) and self.app is not None)
        if on:
            self._geo_backup = self.geometry()
            self.showMaximized()
            if self.lines:
                self._demo_on = not self._follow_active()
                self._demo_pos = float(self.lines[0][0])
                self._play_idx = -1
                self.preview.set_center(0)
                self.preview.set_prog(0.0)
                self._last_mono = time.monotonic()
        else:
            self._demo_on = False
            if self._geo_backup is not None:
                self.showNormal()
                self.setGeometry(self._geo_backup)
            self._on_table_select()

    # ================================================================ 存档
    def _build_data(self):
        if self.rec is None:
            return None
        lines = [[round(max(0.0, float(t)), 2), s] for t, s in self.lines if str(s).strip()]
        if not lines:
            QMessageBox.warning(self, "无法保存", "所有歌词行都是空的，至少保留一句。")
            return None
        data = dict(self.meta)
        data["lines"] = lines
        try:
            data["offset"] = round(float(self.meta.get("offset") or 0.0), 2)
        except (TypeError, ValueError):
            data["offset"] = 0.0
        data.setdefault("title", self.rec.title)
        data.setdefault("artist", self.rec.artist)
        data["saved_at"] = time.strftime("%Y-%m-%d %H:%M")
        return data

    def _problems(self):
        if not self.lines:
            return ["没有任何歌词行"]
        out = []
        for i in range(1, len(self.lines)):
            if self.lines[i][0] < self.lines[i - 1][0] - 1e-9:
                out.append("第 %d 句（%s）早于上一句（%s）"
                           % (i + 1, ll.fmt_time(self.lines[i][0]), ll.fmt_time(self.lines[i - 1][0])))
        empty = [i + 1 for i, (_t, s) in enumerate(self.lines) if not s.strip()]
        if empty:
            out.append("空歌词行：" + "、".join("第 %d 句" % e for e in empty[:8]))
        same = [i + 1 for i in range(1, len(self.lines))
                if abs(self.lines[i][0] - self.lines[i - 1][0]) < 0.02]
        if same:
            out.append("时间几乎重叠：" + "、".join("第 %d 句" % e for e in same[:8]))
        return out

    def _is_current_path(self, path):
        title, artist = self.current_track()
        if not title:
            return False
        try:
            return str(self.lib.target_path(title, artist)).lower() == str(path).lower()
        except Exception:
            return False

    def save(self, silent=False):
        if self.rec is None:
            return False
        data = self._build_data()
        if data is None:
            return False
        problems = self._problems()
        if problems and not silent:
            msg = "保存前请注意：\n\n" + "\n".join("• " + p for p in problems[:8])
            msg += "\n\n仍然保存吗？（也可以先点『按时间排序』）"
            if QMessageBox.question(self, "保存歌词", msg) != QMessageBox.Yes:
                self._hint("已取消保存")
                return False
        path = self.rec.path
        try:
            disk_mtime = path.stat().st_mtime
        except OSError:
            disk_mtime = 0.0
        if self.rec.mtime and disk_mtime > self.rec.mtime + 0.5 and not silent:
            if QMessageBox.question(
                    self, "文件已被更新",
                    "这个文件在打开之后被播放器重新写过，仍然用当前内容覆盖吗？") != QMessageBox.Yes:
                return False
        if not ll.save_record(path, data):
            QMessageBox.warning(self, "保存失败", "无法写入文件：\n%s" % path)
            return False
        row = self.table.currentRow()
        new = self.lib.reload_one(path)
        if new is not None:
            self.rec = new
            self.meta = {k: v for k, v in new.data.items() if k != "lines"}
            self.lines = [[t, s] for t, s in new.lines]
        self.dirty = False
        self._fill_table(keep_row=max(0, row))
        self._render_header()
        self._update_buttons()
        self._refresh_list_row()
        self._hint("已保存 %s" % path.name)
        if self._is_current_path(path) and self.app is not None:
            try:
                self.app.reload_record(data)
            except Exception:
                pass
        return True

    def _refresh_list_row(self):
        if self.rec is None:
            return
        for i in range(self.list.count()):
            it = self.list.item(i)
            rec = it.data(Qt.UserRole)
            if rec is not None and rec.path == self.rec.path:
                it.setData(Qt.UserRole, self.rec)
                break
        self.list.viewport().update()

    def _save_as(self):
        if self.rec is None:
            return
        data = self._build_data()
        if data is None:
            return
        start = str(self.rec.path)
        path, _f = QFileDialog.getSaveFileName(self, "另存为歌词 JSON", start, "歌词 JSON (*.json)")
        if not path:
            return
        if not ll.save_record(path, data):
            QMessageBox.warning(self, "保存失败", "无法写入：\n%s" % path)
            return
        self.lib.reload()
        rec = self.lib.reload_one(path)
        if rec is not None:
            self.load_record(rec)
            self._run_search()
        self._hint("已另存为 %s" % Path(path).name)

    def _delete(self):
        if self.rec is None:
            return
        rec = self.rec
        extra = "\n注意：这是当前正在播放歌曲的歌词文件。" if self._is_current_path(rec.path) else ""
        if QMessageBox.question(self, "删除歌词文件",
                                "确定删除 %s 吗？此操作不可撤销。%s" % (rec.path.name, extra)) != QMessageBox.Yes:
            return
        if not self.lib.remove(rec):
            QMessageBox.warning(self, "删除失败", "无法删除 %s" % rec.path)
            return
        name = rec.path.name
        self.rec = None
        self.lines = []
        self.meta = {}
        self.dirty = False
        self.lib.reload()
        self._update_stats()
        self._fill_table()
        self._render_header()
        self._run_search()
        self.preview.set_data([], 0, "", "")
        self._hint("已删除 %s" % name)

    def _apply_to_current(self):
        if self.rec is None or self.app is None:
            return
        if self.dirty and not self.save():
            return
        title, artist = self.current_track()
        if not title:
            self._hint("当前没有在播放的歌曲，无法匹配")
            return
        data = self._build_data()
        if data is None:
            return
        data["title"], data["artist"] = title, artist
        target = self.lib.target_path(title, artist)
        if target.exists() and not self._is_current_path(target):
            if QMessageBox.question(self, "覆盖已有缓存",
                                    "已经存在 %s，要用当前歌词覆盖它吗？" % target.name) != QMessageBox.Yes:
                return
        if not ll.save_record(target, data):
            QMessageBox.warning(self, "匹配失败", "无法写入：\n%s" % target)
            return
        self.lib.reload()
        rec = self.lib.reload_one(target)
        if rec is not None:
            self.load_record(rec)
        self._run_search()
        try:
            self.app.reload_record(data)
        except Exception:
            pass
        self._hint("已匹配给《%s · %s》→ %s" % (title, artist or "未知歌手", target.name))

    # ================================================================ 杂项
    def _guard(self):
        """有未保存修改时先问一句，返回是否继续切换"""
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("尚未保存")
        box.setIcon(QMessageBox.Question)
        box.setText("当前歌词有未保存的修改。")
        b_save = box.addButton("保存后继续", QMessageBox.AcceptRole)
        box.addButton("放弃修改", QMessageBox.DestructiveRole)
        b_cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_save)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is b_save:
            return self.save()
        if clicked is b_cancel:
            return False
        self.dirty = False
        return True

    def _update_buttons(self):
        has = self.rec is not None and bool(self.lines)
        self.btn_save.setEnabled(has and self.dirty)
        self.btn_as.setEnabled(has)
        self.btn_del.setEnabled(self.rec is not None)
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_redo.setEnabled(bool(self._redo))
        self.btn_sort.setEnabled(has)
        self.btn_beat.setEnabled(has)
        self.btn_back.setEnabled(has)
        self.btn_fwd.setEnabled(has)
        self.btn_play.setEnabled(has)
        self.btn_rewind.setEnabled(has)
        title, artist = self.current_track()
        if self.app is None:
            self.btn_apply.setEnabled(False)
            self.btn_apply.setText("匹配给正在播放")
            self.btn_apply.setToolTip("离线模式：请从水印面板的『歌词编辑』打开本窗口")
        elif has and title:
            self.btn_apply.setEnabled(True)
            self.btn_apply.setText("匹配给《%s》" % (title if len(title) <= 9 else title[:8] + "…"))
            self.btn_apply.setToolTip("把当前歌词写成 %s" % self.lib.target_path(title, artist).name)
        else:
            self.btn_apply.setEnabled(False)
            self.btn_apply.setText("匹配给正在播放")
            self.btn_apply.setToolTip("当前没有在播放的歌曲" if not title else "先选一个歌词文件")
        self.lbl_dirty.setText("● 有未保存的修改" if self.dirty else "")

    def _default_hint(self):
        self.lbl_hint.setText("双击时间或歌词可直接修改 · 选中后按 [ ] 逐句微调 · T 打点 · Ctrl+S 保存（改动前自动备份到 .备份）")

    def _hint(self, text):
        self.lbl_hint.setText(text)
        self._hint_timer.start(6000)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._set_row_style(self._play_idx)

    def showEvent(self, e):
        super().showEvent(e)
        self._last_mono = time.monotonic()
        if not self._clock_timer.isActive():
            self._clock_timer.start()

    def closeEvent(self, e):
        if not self._guard():
            e.ignore()
            return
        self._clock_timer.stop()
        e.accept()


# ==================================================================== 独立运行
def _shot(path, demo=False, query=""):
    win = LyricEditor(None)
    win.resize(1180, 860)
    win.show()
    QApplication.processEvents()
    if query:
        win.search.setText(query)
        win._run_search()
    if win.list.count():
        win.list.setCurrentRow(0)
    QApplication.processEvents()

    def grab():
        if demo:
            win.toggle_demo(True)
            QApplication.processEvents()
            win.resize(1180, 720)
            QApplication.processEvents()
            QTimer.singleShot(500, lambda: (win.grab().save(path), QApplication.quit()))
        else:
            win.grab().save(path)
            QApplication.quit()

    QTimer.singleShot(500, grab)
    return QApplication.instance().exec_()


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName("歌词缓存工坊")
    if "--shot" in argv:
        i = argv.index("--shot")
        out = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-") else "预览-歌词工坊.png"
        query = ""
        if "--query" in argv:
            j = argv.index("--query")
            query = argv[j + 1] if len(argv) > j + 1 else ""
        return _shot(out, demo="--demo" in argv, query=query)
    win = LyricEditor(None)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
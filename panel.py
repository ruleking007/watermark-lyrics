# -*- coding: utf-8 -*-
"""桌面控制卡片：开关 / 不透明度 / 字号 / 行数 / 位置"""
from PyQt5.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, Qt,
                          pyqtProperty, pyqtSignal)
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QLabel, QToolButton,
                             QVBoxLayout, QWidget)

from config import ACCENT, BORDER, TEXT, TEXT_SUB
from uiutil import ui_font

def build_qss():
    """样式表必须在 QApplication 之后构建（QFontDatabase 依赖实例）"""
    return f"""
#card {{
    background: #FBFBFD;
    border: 1px solid rgba(20,22,26,0.07);
    border-radius: 16px;
}}
QLabel {{ background: transparent; color: {TEXT}; font-family: "{ui_font()}"; }}
QLabel#title {{ font-size: 13px; font-weight: 600; }}
QLabel#rowlab {{ font-size: 12px; }}
QLabel#rowval {{ font-size: 11px; color: {TEXT_SUB}; }}
QLabel#song {{ font-size: 12px; font-weight: 500; }}
QLabel#songs {{ font-size: 11px; color: {TEXT_SUB}; }}
QLabel#hint {{ font-size: 11px; color: {TEXT_SUB}; }}
QToolButton {{
    border: none; background: transparent; color: {TEXT_SUB};
    font-size: 13px; border-radius: 6px;
}}
QToolButton:hover {{ background: rgba(20,22,26,0.06); }}
"""


class Switch(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._phase = 0.0
        self._anim = QPropertyAnimation(self, b"phase", self)
        self._anim.setDuration(170)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._phase)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_phase(self):
        return self._phase

    def set_phase(self, v):
        self._phase = float(v)
        self.update()

    phase = pyqtProperty(float, get_phase, set_phase)

    def set_checked_silent(self, on):
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._phase = 1.0 if on else 0.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        on, off = QColor(ACCENT), QColor("#D2D5DB")
        t = self._phase
        col = QColor(int(off.red() + (on.red() - off.red()) * t),
                     int(off.green() + (on.green() - off.green()) * t),
                     int(off.blue() + (on.blue() - off.blue()) * t))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRect(0, 0, w, h), h / 2, h / 2)
        # 滑块
        r = h - 4
        x = 2 + t * (w - r - 4)
        p.setBrush(QColor(0, 0, 0, 18))
        p.drawEllipse(QRectF(x + 0.5, 3, r, r))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, 2, r, r))


class MiniSlider(QWidget):
    """自绘滑块，避免 QSS 子控件在不同 DPI 下尺寸失控"""
    valueChanged = pyqtSignal(int)

    def __init__(self, lo, hi, value, parent=None):
        super().__init__(parent)
        self._lo, self._hi = lo, hi
        self._v = int(value)
        self.setFixedHeight(18)
        self.setMinimumWidth(80)
        self.setCursor(Qt.PointingHandCursor)

    def value(self):
        return self._v

    def setValue(self, v):
        v = max(self._lo, min(self._hi, int(v)))
        if v != self._v:
            self._v = v
            self.update()
            self.valueChanged.emit(v)

    def _track(self):
        return QRectF(7, self.height() / 2 - 1.5, max(20, self.width() - 14), 3)

    def _ratio(self):
        return (self._v - self._lo) / float(max(1, self._hi - self._lo))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        r = self._ratio()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E6E8EC"))
        p.drawRoundedRect(t, 1.5, 1.5)
        if r > 0:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(t.left(), t.top(), max(3.0, t.width() * r), t.height()),
                              1.5, 1.5)
        cx, cy = t.left() + t.width() * r, self.height() / 2.0
        p.setBrush(QColor(20, 24, 32, 26))
        p.drawEllipse(QPointF(cx, cy + 1), 6.4, 6.4)
        p.setBrush(QColor("#FFFFFF"))
        pen = QPen(QColor(ACCENT))
        pen.setWidthF(2.0)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), 5.4, 5.4)

    def mousePressEvent(self, e):
        self._seek(e.pos().x())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._seek(e.pos().x())

    def _seek(self, x):
        t = self._track()
        self.setValue(round(self._lo + (x - t.left()) / t.width() * (self._hi - self._lo)))


class SliderRow(QWidget):
    def __init__(self, label, lo, hi, value, suffix="", parent=None):
        super().__init__(parent)
        self.suffix = suffix
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.lab = QLabel(label)
        self.lab.setObjectName("rowlab")
        self.val = QLabel()
        self.val.setObjectName("rowval")
        top.addWidget(self.lab)
        top.addStretch(1)
        top.addWidget(self.val)
        self.slider = MiniSlider(lo, hi, value)
        self.slider.valueChanged.connect(self._sync_val)
        lay.addLayout(top)
        lay.addWidget(self.slider)
        self._sync_val(value)

    def _sync_val(self, v):
        self.val.setText(f"{v}{self.suffix}")

    def value(self):
        return self.slider.value()

    def set_value_silent(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(int(v))
        self.slider.blockSignals(False)
        self._sync_val(self.slider.value())


class CornerPicker(QWidget):
    SIGNS = {"tl": (-1, -1), "tr": (1, -1), "bl": (-1, 1), "br": (1, 1)}

    def __init__(self, value="br", parent=None):
        super().__init__(parent)
        self.setFixedSize(74, 48)
        self.setCursor(Qt.PointingHandCursor)
        self.value = value

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        p.fillPath(path, QColor("#F4F5F7"))
        p.setPen(QColor(BORDER))
        p.drawPath(path)
        sx, sy = self.SIGNS[self.value]
        bw, bh = 26, 5
        x = 6 if sx < 0 else self.width() - bw - 6
        y0 = 7 if sy < 0 else self.height() - 6 * 3 - 7
        p.setPen(Qt.NoPen)
        for i in range(3):
            c = QColor(ACCENT)
            c.setAlpha(255 - i * 82)
            p.setBrush(c)
            w = bw if i else bw * 0.82
            xx = x if sx < 0 else self.width() - w - 6
            p.drawRoundedRect(QRectF(xx, y0 + i * 7, w, bh), 2.5, 2.5)

    def mousePressEvent(self, e):
        cx, cy = self.width() / 2, self.height() / 2
        key = ("t" if e.pos().y() < cy else "b") + ("l" if e.pos().x() < cx else "r")
        self.value = key
        self.update()
        self.changed(key)

    def changed(self, key):
        pass


class Segmented(QWidget):
    """两态小分段控件"""
    changed = pyqtSignal(str)

    def __init__(self, options, value, parent=None):
        super().__init__(parent)
        self.setObjectName("seg")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(28)
        self.setStyleSheet(f"""
QWidget#seg {{ background:#F1F2F5; border-radius:8px; }}
QToolButton {{ border:none; background:transparent; color:{TEXT_SUB};
               font-size:11px; padding:2px 9px; border-radius:6px; }}
QToolButton:checked {{ background:#FFFFFF; color:{TEXT}; }}
""")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(1)
        for key, label in options:
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(22)
            b.setChecked(key == value)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            lay.addWidget(b)


class Panel(QWidget):
    changed = pyqtSignal(str)
    quit_requested = pyqtSignal()
    edit_requested = pyqtSignal(bool)
    boot_requested = pyqtSignal(bool)
    hide_requested = pyqtSignal()
    offset_delta = pyqtSignal(float)
    offset_reset = pyqtSignal()
    editor_requested = pyqtSignal()

    def __init__(self, cfg):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet(build_qss())
        self._drag = None
        self._off = None
        self._editing = False
        self._now = ("", "", False)
        self._src = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(318)
        self.card.setCursor(Qt.SizeAllCursor)
        outer.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(16, 13, 16, 14)
        body.setSpacing(0)

        # ---- 标题栏（可拖动）
        self.head = DragArea(self)
        head_lay = QHBoxLayout(self.head)
        head_lay.setContentsMargins(0, 0, 0, 0)
        head_lay.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background:{ACCENT}; border-radius:3px;")
        self.title = QLabel("水印歌词")
        self.title.setObjectName("title")
        head_lay.addWidget(dot)
        head_lay.addWidget(self.title)
        head_lay.addStretch(1)
        self.btn_fold = QToolButton()
        self.btn_fold.setText("－")
        self.btn_fold.setFixedSize(22, 22)
        self.btn_fold.setCursor(Qt.PointingHandCursor)
        self.btn_fold.clicked.connect(self.toggle_fold)
        self.btn_close = QToolButton()
        self.btn_close.setText("✕")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setToolTip("隐藏面板（水印继续显示，托盘图标可调回来）")
        self.btn_close.clicked.connect(self.hide_requested.emit)
        head_lay.addWidget(self.btn_fold)
        head_lay.addWidget(self.btn_close)
        body.addWidget(self.head)
        body.addSpacing(11)

        # ---- 主开关
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        col = QVBoxLayout()
        col.setSpacing(1)
        lab = QLabel("显示桌面水印")
        lab.setObjectName("rowlab")
        sub = QLabel("仿 Windows 未激活水印")
        sub.setObjectName("rowval")
        col.addWidget(lab)
        col.addWidget(sub)
        row.addLayout(col)
        row.addStretch(1)
        self.switch = Switch()
        self.switch.toggled.connect(self._on_toggled)
        row.addWidget(self.switch, 0, Qt.AlignVCenter)
        body.addLayout(row)

        # ---- 开机自启
        arow = QHBoxLayout()
        arow.setContentsMargins(0, 6, 0, 0)
        acol = QVBoxLayout()
        acol.setSpacing(1)
        alab = QLabel("开机自启")
        alab.setObjectName("rowlab")
        asub = QLabel("登录 Windows 后自动运行")
        asub.setObjectName("rowval")
        acol.addWidget(alab)
        acol.addWidget(asub)
        arow.addLayout(acol)
        arow.addStretch(1)
        self.switch_boot = Switch()
        self.switch_boot.toggled.connect(self._on_boot)
        arow.addWidget(self.switch_boot, 0, Qt.AlignVCenter)
        body.addLayout(arow)

        # ---- 折叠区
        self.details = QWidget()
        d = QVBoxLayout(self.details)
        d.setContentsMargins(0, 0, 0, 0)
        d.setSpacing(0)

        d.addSpacing(11)
        d.addWidget(self._sep())
        d.addSpacing(10)

        self.song = QLabel("未在播放")
        self.song.setObjectName("song")
        self.song_sub = QLabel("等待网易云音乐…")
        self.song_sub.setObjectName("songs")
        d.addWidget(self.song)
        d.addWidget(self.song_sub)

        d.addSpacing(10)
        d.addWidget(self._sep())
        d.addSpacing(11)

        self.sl_opacity = SliderRow("不透明度", 15, 100, cfg["opacity"], "%")
        self.sl_size = SliderRow("字号", 12, 40, cfg["font_size"], "px")
        self.sl_lines = SliderRow("歌词行数", 1, 9, cfg["line_count"], " 行")
        for w in (self.sl_opacity, self.sl_size, self.sl_lines):
            d.addWidget(w)
            d.addSpacing(8)
        self.sl_opacity.slider.valueChanged.connect(lambda v: self._set("opacity", v))
        self.sl_size.slider.valueChanged.connect(lambda v: self._set("font_size", v))
        self.sl_lines.slider.valueChanged.connect(self._on_lines)

        krow = QHBoxLayout()
        krow.setContentsMargins(0, 0, 0, 0)
        klab = QLabel("已唱着色")
        klab.setObjectName("rowlab")
        krow.addWidget(klab)
        krow.addStretch(1)
        current = ("off" if not cfg["karaoke"]
                   else ("accent" if cfg["karaoke_color"] == "accent" else "main"))
        self.karaoke = Segmented([("off", "关"), ("main", "高亮"), ("accent", "红")], current)
        self.karaoke.changed.connect(self._on_karaoke)
        krow.addWidget(self.karaoke, 0, Qt.AlignVCenter)
        d.addLayout(krow)
        d.addSpacing(4)

        # ---- 对时：词曲不同步时手动前移/后移
        orow = QHBoxLayout()
        orow.setContentsMargins(0, 0, 0, 0)
        olab = QLabel("歌词对时")
        olab.setObjectName("rowlab")
        orow.addWidget(olab)
        orow.addStretch(1)
        self.btn_back = self._pill("−0.5s")
        self.lbl_offset = self._pill("0.0s")
        self.btn_fwd = self._pill("+0.5s")
        self.lbl_offset.setToolTip("点击归零")
        for b in (self.btn_back, self.lbl_offset, self.btn_fwd):
            orow.addWidget(b, 0, Qt.AlignVCenter)
        d.addLayout(orow)
        d.addSpacing(10)
        self.btn_back.clicked.connect(lambda: self.offset_delta.emit(-0.5))
        self.btn_fwd.clicked.connect(lambda: self.offset_delta.emit(0.5))
        self.lbl_offset.clicked.connect(self.offset_reset.emit)
        self._offset = 0.0
        self.set_offset(0.0, False)

        prow = QHBoxLayout()
        prow.setContentsMargins(0, 0, 0, 0)
        plab = QLabel("水印位置")
        plab.setObjectName("rowlab")
        prow.addWidget(plab)
        prow.addStretch(1)
        self.ink = Segmented([("white", "白字"), ("dark", "黑字")], cfg.get("ink") or "white")
        self.ink.changed.connect(self._on_ink)
        prow.addWidget(self.ink, 0, Qt.AlignVCenter)
        prow.addSpacing(6)
        self.corner = CornerPicker(cfg["corner"])
        self.corner.changed = self._on_corner
        prow.addWidget(self.corner, 0, Qt.AlignVCenter)
        d.addLayout(prow)

        d.addSpacing(10)
        d.addWidget(self._sep())
        d.addSpacing(10)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self.btn_edit = QToolButton()
        self.btn_edit.setText("调整位置")
        self.btn_edit.setCursor(Qt.PointingHandCursor)
        self.btn_edit.setStyleSheet(
            f"QToolButton{{border:none;background:#F3F4F7;color:{TEXT};"
            f"font-size:11px;padding:6px 10px;border-radius:8px;}}"
            f"QToolButton:hover{{background:#EAECF0;}}")
        self.btn_edit.clicked.connect(self._toggle_edit)
        self.btn_lib = QToolButton()
        self.btn_lib.setText("歌词编辑")
        self.btn_lib.setCursor(Qt.PointingHandCursor)
        self.btn_lib.setToolTip("搜索歌词缓存、逐句对时，并把选中的版本匹配给正在播放的歌")
        self.btn_lib.setStyleSheet(
            f"QToolButton{{border:none;background:#F3F4F7;color:{TEXT};"
            f"font-size:11px;padding:6px 10px;border-radius:8px;}}"
            f"QToolButton:hover{{background:#EAECF0;}}")
        self.btn_lib.clicked.connect(self.editor_requested.emit)
        self.btn_quit = QToolButton()
        self.btn_quit.setText("退出")
        self.btn_quit.setCursor(Qt.PointingHandCursor)
        self.btn_quit.setStyleSheet(
            f"QToolButton{{border:none;background:transparent;color:{TEXT_SUB};"
            f"font-size:11px;padding:6px 8px;border-radius:8px;}}"
            f"QToolButton:hover{{background:#F3F4F7;}}")
        self.btn_quit.clicked.connect(self.quit_requested.emit)
        foot.addWidget(self.btn_edit)
        foot.addWidget(self.btn_lib)
        foot.addStretch(1)
        foot.addWidget(self.btn_quit)
        d.addLayout(foot)

        body.addWidget(self.details)
        if cfg["collapsed"]:
            self.details.setVisible(False)

        self.adjustSize()
        self._place()
        self._clamp()
        self.switch.set_checked_silent(bool(cfg["enabled"]))

    # ------------------------------------------------------------ 组件
    @staticmethod
    def _sep():
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{BORDER}; border:none;")
        return line

    def _set(self, key, value):
        self.cfg[key] = value
        self.cfg.save()
        self.changed.emit(key)

    def _on_toggled(self, on):
        self.cfg["enabled"] = bool(on)
        self.cfg.save()
        self.changed.emit("enabled")

    def _on_corner(self, key):
        self.cfg["corner"] = key
        self.cfg["edge_dx"] = None
        self.cfg["edge_dy"] = None
        self.cfg["pos_x"] = None
        self.cfg["pos_y"] = None
        self.cfg.save()
        self.changed.emit("corner")

    def set_corner(self, key):
        """水印被拖到别的角时同步选择器"""
        self.corner.value = key
        self.corner.update()

    def _on_ink(self, key):
        self.cfg["ink"] = key
        self.cfg.save()
        self.changed.emit("ink")

    def _on_lines(self, v):
        """行数只取奇数：当前句必须居中，两侧对称才有上下文"""
        v = int(v)
        if v % 2 == 0:
            v = min(9, v + 1)
        if v != int(self.cfg["line_count"]):
            self.cfg["line_count"] = v
            self.cfg.save()
            self.changed.emit("line_count")
        if int(self.sl_lines.value()) != v:
            self.sl_lines.set_value_silent(v)

    def _on_karaoke(self, key):
        if key == "off":
            self.cfg["karaoke"] = False
        else:
            self.cfg["karaoke"] = True
            self.cfg["karaoke_color"] = key
        self.cfg.save()
        self.changed.emit("karaoke")

    def _on_boot(self, on):
        self.boot_requested.emit(bool(on))

    def set_boot_state(self, on):
        self.switch_boot.set_checked_silent(bool(on))

    def _apply_edit_ui(self):
        on = self._editing
        self.btn_edit.setText("完成调整" if on else "调整位置")
        self.btn_edit.setStyleSheet(
            f"QToolButton{{border:none;background:{ACCENT};color:#fff;"
            f"font-size:11px;padding:6px 10px;border-radius:8px;}}"
            if on else
            f"QToolButton{{border:none;background:#F3F4F7;color:{TEXT};"
            f"font-size:11px;padding:6px 10px;border-radius:8px;}}")

    def set_edit_state(self, on):
        """由水印层点"完成"后回调，保证按钮状态一致"""
        self._editing = bool(on)
        self._apply_edit_ui()

    def _toggle_edit(self):
        self._editing = not self._editing
        self._apply_edit_ui()
        self.edit_requested.emit(self._editing)

    # ------------------------------------------------------------ 状态同步
    def paintEvent(self, _):
        """手绘投影：QGraphicsDropShadowEffect 会缓存子控件旧帧，改样式后留残影"""
        g = self.card.geometry()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i in range(14, 0, -1):
            p.setBrush(QColor(18, 22, 30, 7))
            r = QRectF(g).adjusted(-i * 0.9, -i * 0.9 + 4, i * 0.9, i * 0.9 + 4)
            p.drawRoundedRect(r, 16 + i * 0.5, 16 + i * 0.5)

    @staticmethod
    def _pill_qss(enabled, accent=False):
        if not enabled:
            return ("QToolButton{border:none;background:#F5F6F8;color:#C3C7CE;"
                    "font-size:11px;padding:5px 9px;border-radius:8px;}")
        color = ACCENT if accent else TEXT
        return (f"QToolButton{{border:none;background:#F3F4F7;color:{color};"
                f"font-size:11px;padding:5px 9px;border-radius:8px;}}"
                f"QToolButton:hover{{background:#EAECF0;}}")

    def _pill(self, text):
        b = QToolButton()
        b.setText(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(self._pill_qss(False))
        return b

    def set_offset(self, value, enabled=True):
        self._offset = round(float(value), 2)
        on = abs(self._offset) > 0.005
        self.lbl_offset.setText(f"{self._offset:+.1f}s" if on else "0.0s")
        for b in (self.btn_back, self.btn_fwd):
            b.setEnabled(enabled)
            b.setStyleSheet(self._pill_qss(enabled))
        self.lbl_offset.setEnabled(enabled)
        self.lbl_offset.setStyleSheet(self._pill_qss(enabled, on))

    def set_lyric_source(self, text):
        self._src = text or ""
        self._render_now()

    def set_now_playing(self, title, artist, playing):
        self._now = (title, artist, playing)
        self._render_now()

    def _render_now(self):
        title, artist, playing = self._now
        if not title:
            self.song.setText("未在播放")
            self.song_sub.setText("打开网易云音乐开始播放")
            return
        self.song.setText(title)
        bits = [artist or "未知歌手", "播放中" if playing else "已暂停"]
        if self._src:
            bits.append(self._src)
        self.song_sub.setText("  ·  ".join(bits))

    def set_enabled(self, on):
        self.switch.set_checked_silent(on)

    def toggle_fold(self):
        show = not self.details.isVisible()
        self.details.setVisible(show)
        self.cfg["collapsed"] = not show
        self.cfg.save()
        self.btn_fold.setText("－" if show else "＋")
        self.adjustSize()
        self._clamp()

    # ------------------------------------------------------------ 位置
    def _place(self):
        from PyQt5.QtWidgets import QApplication
        geo = (QApplication.primaryScreen() or QApplication.screens()[0]).availableGeometry()
        x, y = self.cfg["panel_x"], self.cfg["panel_y"]
        if x is None or y is None:
            # 默认贴右上，避开右下角的水印
            x = geo.right() - self.width() - 30
            y = geo.top() + 72
        self.move(int(x), int(y))

    def persist_pos(self):
        self.cfg["panel_x"] = self.x()
        self.cfg["panel_y"] = self.y()
        self.cfg.save()

    def _clamp(self):
        """卡片变高后别顶出屏幕"""
        from PyQt5.QtWidgets import QApplication
        scr = QApplication.primaryScreen() or QApplication.screens()[0]
        geo = scr.availableGeometry()
        x = max(geo.left(), min(self.x(), geo.right() - self.width() - 4))
        y = max(geo.top(), min(self.y(), geo.bottom() - self.height() - 4))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # 整张卡片都能拖着走（控件自己会吃掉事件，空白处冒泡到这里）
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._off is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._off)

    def mouseReleaseEvent(self, e):
        if self._off is not None:
            self._off = None
            self.persist_pos()


class DragArea(QWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self._off = None
        self.setCursor(Qt.SizeAllCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._off = e.globalPos() - self.panel.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._off is not None:
            self.panel.move(e.globalPos() - self._off)

    def mouseReleaseEvent(self, e):
        if self._off is not None:
            self._off = None
            self.panel.persist_pos()

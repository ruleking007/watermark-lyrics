# -*- coding: utf-8 -*-
"""水印歌词层：无边框 / 逐像素透明 / 鼠标穿透 / 置顶，仿 Windows 未激活水印排版"""
import ctypes
import math

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import QApplication, QWidget

from config import ACCENT
from uiutil import ui_font

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SWP_FLAGS = 0x0002 | 0x0001 | 0x0004 | 0x0020  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED


class LyricOverlay(QWidget):
    MAX_W_RATIO = 0.62
    PAD_R = 14
    edit_finished = pyqtSignal()
    anchor_changed = pyqtSignal(str)

    def __init__(self, cfg):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                 | Qt.NoDropShadowWindowHint)
        super().__init__(None, flags)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.family = ui_font()

        self.lines = []      # [(秒, 文本)]
        self.title = ""
        self.artist = ""
        self.idx = 0         # 目标行
        self.disp = 0.0      # 显示行(带动画)
        self.prog = 0.0      # 当前行已唱比例
        self.master = 0.0    # 整体淡入淡出
        self.edit = False
        self._drag = None
        self._screen_geo = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

        self._apply_geometry()

    # ------------------------------------------------------------ 对外接口
    def set_track(self, title, artist):
        self.title, self.artist = title, artist
        self.refresh_style()

    def set_lines(self, lines):
        self.lines = lines or []
        self.idx = 0
        self.disp = 0.0
        self.refresh_style()

    def set_index(self, idx):
        if idx != self.idx:
            self.idx = idx

    def set_progress(self, p):
        if abs(p - self.prog) > 0.0015:
            self.prog = p
            if self.cfg["karaoke"]:
                self.update()

    def refresh_style(self):
        base, lh, n, h = self._metrics()
        self.resize(self._calc_width(), h)
        self._place()
        self.update()

    def begin_edit(self, on):
        self.edit = bool(on)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        self.setCursor(Qt.SizeAllCursor if on else Qt.ArrowCursor)
        self._win32_styles()
        self._place()
        self.update()

    # ------------------------------------------------------------ 定位
    def _metrics(self):
        base = int(self.cfg["font_size"])
        lh = base * 1.66
        n = max(1, int(self.cfg["line_count"]))
        meta = int(base * 0.72) if self.cfg["show_meta"] else 0
        h = int(n * lh + meta * 1.9 + 24)
        return base, lh, n, h

    def _calc_width(self):
        """窗口宽度贴合最长一句，像水印一样贴着文字"""
        base = int(self.cfg["font_size"])
        maxw = 0
        if self.lines:
            f = QFont(self.family)
            f.setPixelSize(base)
            f.setWeight(QFont.DemiBold)
            fm = QFontMetrics(f)
            for _, s in self.lines[:40]:
                maxw = max(maxw, fm.horizontalAdvance(s))
        elif self.title:
            f = QFont(self.family)
            f.setPixelSize(int(base * 0.92))
            maxw = max(maxw, QFontMetrics(f).horizontalAdvance(
                f"♪ {self.title} — {self.artist}"))
        if self.lines and self.cfg["show_meta"] and self.title:
            f = QFont(self.family)
            f.setPixelSize(max(9, int(base * 0.62)))
            maxw = max(maxw, QFontMetrics(f).horizontalAdvance(
                f"{self.title} · {self.artist}"))
        scr = QApplication.primaryScreen()
        cap = int((scr.availableGeometry().width() if scr else 1920) * self.MAX_W_RATIO)
        return int(max(240, min(maxw + self.PAD_R + 8, cap)))

    def _apply_geometry(self):
        base, lh, n, h = self._metrics()
        self.resize(self._calc_width(), h)
        self._place()

    def _anchor(self, geo):
        """返回贴边距离(dx,dy)。只记距离不记绝对坐标，宽度变化时贴边侧才不会跑"""
        corner = self.cfg["corner"]
        right, bottom = "r" in corner, "b" in corner
        dx, dy = self.cfg.get("edge_dx"), self.cfg.get("edge_dy")
        if dx is None or dy is None:
            px, py = self.cfg.get("pos_x"), self.cfg.get("pos_y")
            if px is not None and py is not None:      # 旧版绝对坐标迁移一次
                dx = (geo.right() - (int(px) + self.width())) if right else (int(px) - geo.left())
                dy = (geo.bottom() - (int(py) + self.height())) if bottom else (int(py) - geo.top())
                # 旧版本换歌会横向漂移，离贴边太远就当作脏数据直接归位（纵向保留）
                if abs(dx) > 200:
                    dx = int(self.cfg["margin"])
                self.cfg["edge_dx"], self.cfg["edge_dy"] = int(dx), int(dy)
                self.cfg["pos_x"] = self.cfg["pos_y"] = None
                self.cfg.save()
            else:
                dx = dy = int(self.cfg["margin"])
        return int(dx), int(dy)

    def _place(self):
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.availableGeometry()
        self._screen_geo = geo
        dx, dy = self._anchor(geo)
        corner = self.cfg["corner"]
        right, bottom = "r" in corner, "b" in corner
        # 贴边侧钉死，宽度变化时往另一侧长（右贴边→向左扩，左贴边→向右扩）
        x = geo.right() - self.width() - dx if right else geo.left() + dx
        y = geo.bottom() - self.height() - dy if bottom else geo.top() + dy
        x = max(geo.left(), min(int(x), max(geo.left(), geo.right() - self.width())))
        y = max(geo.top(), min(int(y), max(geo.top(), geo.bottom() - self.height())))
        self.move(int(x), int(y))

    @staticmethod
    def _corner_for(geo, x, y, w, h):
        cx, cy = x + w / 2.0, y + h / 2.0
        return ("t" if cy < geo.center().y() else "b") + ("l" if cx < geo.center().x() else "r")


    def _win32_styles(self):
        """统一维护扩展样式：编辑时接受鼠标，平时鼠标穿透且不抢焦点"""
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new = cur | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if self.edit:
                new &= ~WS_EX_TRANSPARENT
            else:
                new |= WS_EX_TRANSPARENT
            if new != cur:
                user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self._win32_styles()

    # ------------------------------------------------------------ 动画
    def _tick(self):
        target = 1.0 if (self.cfg["enabled"] and (self.lines or self.title)) else 0.0
        changed = False
        if abs(self.master - target) > 0.004:
            self.master += (target - self.master) * 0.14
            changed = True
        elif self.master != target:
            self.master = target
            changed = True
        if abs(self.disp - self.idx) > 0.004:
            self.disp += (self.idx - self.disp) * 0.17
            changed = True
        elif self.disp != self.idx:
            self.disp = float(self.idx)
            changed = True
        if changed:
            self.update()
        if not self.visibleRegion().isEmpty() and not self.edit:
            geo = QApplication.primaryScreen().availableGeometry()
            if geo != self._screen_geo:
                self._apply_geometry()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, _):
        if self.master <= 0.01 and not self.edit:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        base, lh, n, h = self._metrics()
        op = max(0.0, min(1.0, self.cfg["opacity"] / 100.0))
        w = self.width() - self.PAD_R

        if self.lines:
            meta_h = int(base * 0.72 * 1.9) if self.cfg["show_meta"] else 0
            mid = (h - meta_h) / 2.0
            half = (n - 1) / 2.0
            lo = int(math.floor(self.disp - half - 0.5))
            hi = int(math.ceil(self.disp + half + 0.5))
            for i in range(lo, hi + 1):
                if i < 0 or i >= len(self.lines):
                    continue
                d = abs(i - self.disp)
                if d > half + 0.5:
                    continue
                y = mid + (i - self.disp) * lh
                cur = d < 0.5
                a = op * self.master * (1.0 if cur else 0.42 ** d)
                if a < 0.012:
                    continue
                size = base * (1.0 if cur else 1.0 - 0.045 * min(d, 1.6))
                # 只有当前行做"已唱/未唱"着色，已唱完的行照常淡出
                if i == self.idx:
                    prog = self.prog if self.cfg["karaoke"] else 1.0
                    tint = bool(self.cfg["karaoke"])
                else:
                    prog = 1.0 if i < self.idx else 0.0
                    tint = False
                self._text(p, self.lines[i][1], size,
                           QFont.DemiBold if cur else QFont.Normal,
                           QRect(0, int(y - lh / 2), w, int(lh)),
                           Qt.AlignRight | Qt.AlignVCenter, a, prog, tint)

            if meta_h:
                meta = f"{self.title}" + (f" · {self.artist}" if self.artist else "")
                self._text(p, meta, base * 0.62, QFont.Normal,
                           QRect(0, h - meta_h - 6, w, meta_h + 6),
                           Qt.AlignRight | Qt.AlignVCenter, op * self.master * 0.55)
        elif self.title:
            label = f"♪ {self.title}" + (f" — {self.artist}" if self.artist else "")
            self._text(p, label, base * 0.92, QFont.Normal,
                       QRect(0, 0, w, h), Qt.AlignRight | Qt.AlignVCenter,
                       op * self.master * 0.85)

        if self.edit:
            # 分层窗口按 alpha 做命中测试，全透明处点不到，所以铺一层极淡底色
            p.setOpacity(1.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(236, 65, 65, 12))
            p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 12, 12)
            p.setOpacity(0.9)
            pen = p.pen()
            pen.setColor(QColor(ACCENT))
            pen.setWidth(2)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 12, 12)
            p.setOpacity(0.55)
            f = QFont(self.family)
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QColor(ACCENT))
            p.drawText(QRect(10, 6, 300, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       "拖动调整位置，松开即保存")
            # 完成按钮：忘了退出时点这里，避免水印一直吃点击
            r = self._done_rect()
            p.setOpacity(1.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(r, 11, 11)
            p.setPen(QColor(255, 255, 255))
            p.drawText(r, Qt.AlignCenter, "完成")

    def _text(self, p, text, size, weight, rect, align, alpha, prog=1.0, tint=False):
        if alpha <= 0.01 or not text:
            return
        f = QFont(self.family)
        f.setPixelSize(max(9, int(round(size))))
        f.setWeight(weight)
        p.setFont(f)
        fm = QFontMetrics(f)
        t = fm.elidedText(text, Qt.ElideRight, rect.width() - 6)
        dark_ink = self.cfg["ink"] == "dark"
        main = QColor(28, 30, 34, 255) if dark_ink else QColor(255, 255, 255, 255)
        halo = QColor(255, 255, 255, 88) if dark_ink else QColor(0, 0, 0, 62)
        sh1 = QColor(255, 255, 255, 110) if dark_ink else QColor(0, 0, 0, 105)
        sh2 = QColor(255, 255, 255, 70) if dark_ink else QColor(0, 0, 0, 60)
        unsung = QColor(main)
        unsung.setAlpha(150)
        if tint and self.cfg["karaoke_color"] == "accent":
            sung = QColor(233, 66, 71, 255)
        else:
            sung = QColor(main)

        p.setOpacity(min(1.0, alpha))
        # 1px 四向描边 + 双层下投影，明暗背景都能读，同时保留水印的柔边
        p.setPen(halo)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.drawText(rect.translated(dx, dy), align, t)
        p.setPen(sh1)
        p.drawText(rect.translated(0, 1), align, t)
        p.setPen(sh2)
        p.drawText(rect.translated(0, 2), align, t)

        full = prog >= 0.999
        if not full:
            p.setPen(unsung)
            p.drawText(rect, align, t)
        if prog > 0.001:
            p.setPen(sung)
            if full:
                p.drawText(rect, align, t)
            else:
                tw = fm.horizontalAdvance(t)
                x0 = rect.right() - tw + 1
                p.save()
                p.setClipRect(QRectF(x0, rect.top() - 4, tw * prog, rect.height() + 8))
                p.drawText(rect, align, t)
                p.restore()

    # ------------------------------------------------------------ 拖动
    def _done_rect(self):
        return QRect(self.width() - 62, 6, 54, 22)
    def mousePressEvent(self, e):
        if not self.edit:
            return
        if self._done_rect().contains(e.pos()):
            self.begin_edit(False)
            self.edit_finished.emit()
            e.accept()
            return
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPos() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self.edit and self._drag is not None:
            self.move(e.globalPos() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        if self.edit and self._drag is not None:
            self._drag = None
            scr = QApplication.primaryScreen()
            if scr is not None:
                geo = scr.availableGeometry()
                key = self._corner_for(geo, self.x(), self.y(), self.width(), self.height())
                changed = key != self.cfg["corner"]
                self.cfg["corner"] = key
                right, bottom = "r" in key, "b" in key
                self.cfg["edge_dx"] = (geo.right() - self.right()) if right else (self.x() - geo.left())
                self.cfg["edge_dy"] = (geo.bottom() - self.bottom()) if bottom else (self.y() - geo.top())
                self.cfg["pos_x"] = self.cfg["pos_y"] = None
                self.cfg.save()
                if changed:
                    self.anchor_changed.emit(key)
            e.accept()

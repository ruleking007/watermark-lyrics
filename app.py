# -*- coding: utf-8 -*-
"""水印歌词 —— 把网易云音乐的桌面歌词做成 Windows 未激活水印的样子"""
import os
import sys
import threading

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QAction, QApplication, QMenu, QSystemTrayIcon

from autostart import is_enabled as boot_enabled, set_enabled as set_boot
from config import Config, ROOT
from core import LYRIC_DIR, LyricClock, LyricService, LyricStore, MediaWorker, split_meta
from overlay import LyricOverlay
from panel import Panel
from uiutil import make_icon


def _detect_ink():
    """读壁纸，估算水印落点明暗：亮壁纸用深色字，暗壁纸用白字"""
    import winreg

    from PyQt5.QtGui import QImage

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as k:
            path = winreg.QueryValueEx(k, "WallPaper")[0]
    except Exception:
        return None
    if not path or not os.path.exists(path):
        return None
    img = QImage(path)
    if img.isNull() or img.width() <= 0:
        return None
    scr = QApplication.primaryScreen()
    if scr is None:
        return None
    geo = scr.availableGeometry()
    sw, sh = geo.width(), geo.height()
    scale = max(sw / img.width(), sh / img.height())
    tw, th = int(img.width() * scale), int(img.height() * scale)
    img = img.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    img = img.copy((tw - sw) // 2, (th - sh) // 2, sw, sh)
    region = img.copy(int(sw * 0.60), int(sh * 0.66),
                      max(1, int(sw * 0.40)), max(1, int(sh * 0.34)))
    c = region.scaled(1, 1, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).pixelColor(0, 0)
    lum = (0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()) / 255.0
    return "dark" if lum > 0.62 else "white"


class App(QObject):
    lyrics_ready = pyqtSignal(tuple, object)

    def __init__(self, qapp):
        super().__init__()
        self.qapp = qapp
        self.cfg = Config()
        if self.cfg.get("ink") not in ("white", "dark"):
            self.cfg["ink"] = _detect_ink() or "white"
            self.cfg.save()
        if int(self.cfg["line_count"]) % 2 == 0:      # 行数只支持奇数
            self.cfg["line_count"] = min(9, int(self.cfg["line_count"]) + 1)
            self.cfg.save()
        self.store = LyricStore()
        self.lyrics = LyricService()
        self.clock = LyricClock()
        self._key = None
        self._meta = {}       # 当前曲的取词信息(source/id/duration)
        self._offset = 0.0    # 当前曲的用户对时偏移
        self._committed = False
        self._hinted = False
        self.editor = None       # 歌词缓存工坊窗口，用到时才建

        self.overlay = LyricOverlay(self.cfg)
        self.panel = Panel(self.cfg)
        self.overlay.show()
        self.panel.show()

        self.panel.changed.connect(self.on_cfg_changed)
        self.panel.quit_requested.connect(self.quit)
        self.panel.edit_requested.connect(self.on_edit_request)
        self.overlay.edit_finished.connect(lambda: self.on_edit_request(False))
        self.overlay.anchor_changed.connect(self.panel.set_corner)
        self.panel.boot_requested.connect(self.on_boot_request)
        self.panel.hide_requested.connect(self.on_hide_panel)
        self.panel.offset_delta.connect(self.on_offset_delta)
        self.panel.offset_reset.connect(self.on_offset_reset)
        self.panel.editor_requested.connect(self.open_editor)
        self.panel.set_boot_state(boot_enabled())
        self.lyrics_ready.connect(self.on_lyrics)

        self._build_tray()

        self.worker = MediaWorker()
        self.worker.track.connect(self.on_track)
        self.worker.start()

        self.timer = QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ------------------------------------------------------------ 托盘
    def _build_tray(self):
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("水印歌词 · 点一下打开面板")

        def show_panel():
            self.panel.show()
            self.panel.raise_()

        self.act_show = QAction("显示桌面水印", self, checkable=True)
        self.act_show.setChecked(bool(self.cfg["enabled"]))
        self.act_show.triggered.connect(self._tray_toggle)

        self.act_panel = QAction("控制面板", self)
        self.act_panel.triggered.connect(show_panel)
        self.act_lib = QAction("歌词编辑 / 缓存工坊", self)
        self.act_lib.triggered.connect(self.open_editor)
        self.act_edit = QAction("调整水印位置", self)
        self.act_edit.triggered.connect(self.toggle_edit)
        self.act_quit = QAction("退出", self)
        self.act_quit.triggered.connect(self.quit)

        menu = QMenu()
        menu.addAction(self.act_show)
        menu.addSeparator()
        menu.addAction(self.act_panel)
        menu.addAction(self.act_lib)
        menu.addAction(self.act_edit)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: show_panel() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _tray_toggle(self, on):
        self.cfg["enabled"] = bool(on)
        self.cfg.save()
        self.panel.set_enabled(on)
        self.on_cfg_changed("enabled")

    # ------------------------------------------------------------ 播放同步
    def on_track(self, payload):
        title, artist = split_meta(payload.get("title", ""), payload.get("artist", ""))
        key = (title, artist)
        if key != self._key:
            self._commit_track()          # 上一首播到一半被切走 → 落盘
            self._key = key
            self.clock.reset()
            self.clock.lines = []
            self.clock.offset = 0.0
            self._offset = 0.0
            self._meta = {}
            self._committed = False
            self.overlay.set_lines([])
            self.overlay.set_index(0)
            self.overlay.set_track(title, artist)
            self.panel.set_offset(0.0, False)
            self.panel.set_lyric_source("")
            if title:
                self._load_track(title, artist)
        self.clock.playing = bool(payload.get("playing"))
        self.panel.set_now_playing(title, artist, self.clock.playing)
        if self.editor is not None and self.editor.isVisible():
            self.editor.sync_track()

    # ------------------------------------------------------------ 歌词缓存工坊
    def current_track(self):
        """给编辑器用：当前正在播放的 (歌名, 歌手)"""
        return self._key if (self._key and self._key[0]) else None

    def open_editor(self):
        from editor import LyricEditor
        if self.editor is None:
            self.editor = LyricEditor(self)
        self.editor.sync_track()
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def reload_record(self, record):
        """编辑器保存了当前歌曲的歌词后立刻刷新水印，不用等下一首"""
        if not record or not record.get("lines"):
            return
        rec = dict(record)
        rec["lines"] = [[float(t), str(s)] for t, s in record["lines"]]
        self._apply_record(rec, cached=True)

    def _load_track(self, title, artist):
        """先翻本地歌词库，命中就完全不联网"""
        rec = self.store.load(title, artist)
        if rec:
            self._apply_record(rec, cached=True)
            return
        threading.Thread(target=self._fetch, args=((title, artist), title, artist),
                         daemon=True).start()

    def _fetch(self, key, title, artist):
        try:
            rec = self.lyrics.resolve(title, artist)
        except Exception:
            rec = None
        if key == self._key:
            self.lyrics_ready.emit(key, rec)

    def on_lyrics(self, key, rec):
        if key != self._key:
            return
        if not rec or not rec.get("lines"):
            self.clock.lines = []
            self.overlay.set_lines([])
            self.panel.set_offset(0.0, False)
            self.panel.set_lyric_source("找不到歌词")
            return
        self._apply_record(rec, cached=False)

    def _apply_record(self, rec, cached):
        lines = rec.get("lines") or []
        self.clock.lines = lines
        self.clock.index = 0
        self._offset = float(rec.get("offset") or 0.0)
        self.clock.offset = self._offset
        self._meta = {k: rec.get(k) for k in ("source", "id", "duration") if rec.get(k)}
        self.overlay.set_lines(lines)
        self.panel.set_offset(self._offset, bool(lines))
        src = {"netease": "网易云", "qq": "QQ音乐"}.get(rec.get("source"), "本地")
        self.panel.set_lyric_source(("本地歌词" if cached else src))

    def _save_track(self, title, artist):
        if not title or not self.clock.lines:
            return
        rec = dict(self._meta)
        rec.update({"title": title, "artist": artist,
                    "offset": round(self._offset, 2),
                    "lines": self.clock.lines,
                    "saved_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")})
        self.store.save(title, artist, rec)

    def _commit_track(self):
        """只有真的放过一段才入库，避免把跳过歌曲的错误匹配存下来"""
        if not self._key or not self.clock.lines:
            return
        if self.clock.pos < 6:
            return
        self._save_track(self._key[0], self._key[1])

    # ------------------------------------------------------------ 对时
    def on_offset_delta(self, delta):
        if not self.clock.lines:
            return
        self._offset = round(max(-30.0, min(30.0, self._offset + delta)), 2)
        self.clock.offset = self._offset
        self.panel.set_offset(self._offset, True)
        if self._key:
            self._save_track(self._key[0], self._key[1])   # 调整结果立刻连同歌词入库

    def on_offset_reset(self):
        if not self.clock.lines or abs(self._offset) < 0.005:
            return
        self._offset = 0.0
        self.clock.offset = 0.0
        self.panel.set_offset(0.0, True)
        if self._key:
            self._save_track(self._key[0], self._key[1])

    def tick(self):
        self.overlay.set_index(self.clock.tick())
        self.overlay.set_progress(self.clock.progress)
        self._maybe_commit()

    def _maybe_commit(self):
        """整首放完就立刻入库（时长来自取词结果），不必等切歌"""
        if self._committed or not self._key or not self.clock.lines:
            return
        dur = self._meta.get("duration") or 0
        if dur and self.clock.pos >= max(20.0, dur - 3.0):
            self._commit_track()
            self._committed = True

    def on_hide_panel(self):
        """✕ 只是把面板收进托盘，水印继续跑"""
        self.panel.hide()
        if not self._hinted:
            self._hinted = True
            self.tray.showMessage("水印歌词", "面板已隐藏，水印继续显示。\n点击托盘图标可以调回面板。",
                                  QSystemTrayIcon.Information, 4000)

    def on_boot_request(self, on):
        set_boot(on)
        self.panel.set_boot_state(boot_enabled())

    def on_edit_request(self, on):
        """调整位置模式的唯一入口，保证面板按钮、托盘菜单、水印三者状态一致"""
        self.overlay.begin_edit(on)
        self.panel.set_edit_state(on)
        self.act_edit.setText("完成调整" if on else "调整水印位置")

    def toggle_edit(self):
        self.on_edit_request(not self.overlay.edit)

    # ------------------------------------------------------------ 设置变更
    def on_cfg_changed(self, name):
        self.overlay.refresh_style()
        if name == "enabled":
            self.overlay.show()
            self.act_show.setChecked(bool(self.cfg["enabled"]))
            self.panel.set_enabled(bool(self.cfg["enabled"]))

    def quit(self):
        try:
            self._commit_track()
        except Exception:
            pass
        try:
            if self.editor is not None:
                self.editor.close()
        except Exception:
            pass
        try:
            self.worker.stop()
        except Exception:
            pass
        self.cfg.save()
        self.tray.hide()
        self.qapp.quit()


def _selftest():
    """离屏自检：渲染两张界面到 PNG，供肉眼确认排版"""
    from PyQt5.QtGui import QColor, QPixmap

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    cfg = Config()
    cfg.update({"enabled": True, "opacity": 62, "font_size": 21, "line_count": 5})

    ov = LyricOverlay(cfg)
    ov.lines = [
        [0.0, "如果可以 我想和你回到那天相遇"],
        [4.0, "让时间停止 那一场雨"],
        [8.0, "只想拥抱 你在身边的证据"],
        [12.0, "吻你的呼吸"],
        [16.0, "一眨眼 一瞬间 你说好就是永远"],
        [20.0, "如果可以 茫茫人海千年一眼相遇"],
    ]
    ov.title, ov.artist = "如果可以", "韦礼安"
    ov.idx = ov.disp = 2
    ov.prog = 0.42
    ov.master = 1.0
    ov.refresh_style()
    w, h = ov.width(), ov.height()
    dpr = max(1.0, float(ov.devicePixelRatioF()))
    for ink, bg, name in (("white", QColor("#1d2026"), "dark"),
                          ("dark", QColor("#f2f0ed"), "light")):
        cfg["ink"] = ink
        ov.refresh_style()
        pm = QPixmap(int(ov.width() * dpr), int(ov.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(bg)
        ov.render(pm)
        pm.save(os.path.join(os.path.dirname(__file__), f"预览-水印-{name}.png"))

    panel = Panel(cfg)
    panel.set_now_playing("如果可以", "韦礼安", True)
    panel.adjustSize()
    pm = QPixmap(int(panel.width() * dpr), int(panel.height() * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor("#8f9aa6"))
    panel.render(pm)
    pm.save(os.path.join(os.path.dirname(__file__), "预览-控制面板.png"))
    print("selftest ok", w, h, panel.width(), panel.height(), "dpr", dpr)
    return 0


def _probe():
    """端到端探针：不显示窗口，验证 SMTC -> 歌词接口 -> 时间轴"""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = App(app)
    w.overlay.hide()
    w.panel.hide()

    def report():
        print("PROBE key=%r lines=%d pos=%.1f idx=%d prog=%.2f playing=%s" % (
            w._key, len(w.clock.lines), w.clock.pos, w.clock.index,
            w.clock.progress, w.clock.playing), flush=True)

    QTimer.singleShot(2500, report)
    QTimer.singleShot(7000, report)
    QTimer.singleShot(7600, lambda: (w.worker.stop(), app.quit()))
    return app.exec_()


def _doctor():
    """排障自检：把环境、依赖、歌词目录、媒体会话写进文本并打印。

    打包成 exe 后没有控制台，所以结果同时落在 %APPDATA%\\WatermarkLyric\\doctor.txt，
    换电脑出问题时把这个文件发出来就能定位。
    """
    import asyncio
    from datetime import datetime

    lines = ["水印歌词 自检  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    lines.append("打包运行(frozen) = %s" % bool(getattr(sys, "frozen", False)))
    lines.append("可执行文件      = %s" % sys.executable)
    lines.append("解释器版本      = %s" % sys.version.replace("\n", " "))
    lines.append("工作目录        = %s" % os.getcwd())
    for mod in ("PyQt5", "requests", "winrt", "winrt.windows.media.control",
                "editor", "lyriclib"):
        try:
            __import__(mod)
            lines.append("[ok]   依赖 %s" % mod)
        except Exception as exc:
            lines.append("[缺失] 依赖 %s -> %r" % (mod, exc))
    try:
        files = sorted(LYRIC_DIR.glob("*.json"))
        lines.append("[ok]   歌词缓存 %s（%d 个 json）" % (LYRIC_DIR, len(files)))
    except Exception as exc:
        lines.append("[缺失] 歌词缓存 %s -> %r" % (LYRIC_DIR, exc))

    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager)

        async def probe_session():
            mgr = await Manager.request_async()
            ses = mgr.get_current_session()
            if ses is None:
                return "当前没有媒体会话（先打开播放器放首歌）"
            props = await ses.try_get_media_properties_async()
            info = ses.get_playback_info()
            return "标题=%r 歌手=%r 应用=%s 播放状态=%s" % (
                props.title, props.artist, ses.source_app_user_model_id, info.playback_status)

        lines.append("[ok]   媒体会话 " + asyncio.run(probe_session()))
    except Exception as exc:
        lines.append("[失败] 媒体会话读取 -> %r" % exc)

    text = "\n".join(lines)
    try:
        (ROOT / "doctor.txt").write_text(text, "utf-8")
    except Exception:
        pass
    print(text)
    return 0


MUTEX_NAME = "WatermarkLyric_SingleInstance_v1"
_mutex = None


def _single_instance(name=MUTEX_NAME):
    """同一时间只允许一个实例，避免出现两层水印。

    必须用 use_last_error + get_last_error 读错误码：ctypes 默认会在
    CreateMutexW 和 GetLastError 之间夹带别的调用，把错误码冲掉，
    结果就是"双开也能起来"，桌面上会出现两层水印、还会互相抢写歌词缓存。
    """
    global _mutex
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    _mutex = kernel32.CreateMutexW(None, False, name)
    if not _mutex:
        return True                       # 句柄都拿不到就别拦着，照常启动
    return ctypes.get_last_error() != 183  # 183 = ERROR_ALREADY_EXISTS


def _install_crash_log():
    from config import ROOT

    def hook(tp, value, tb):
        import traceback
        try:
            with open(ROOT / "error.log", "a", encoding="utf-8") as f:
                f.write("----- " + __import__("datetime").datetime.now().isoformat() + "\n")
                traceback.print_exception(tp, value, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(tp, value, tb)

    sys.excepthook = hook


def main():
    if "--selftest" in sys.argv:
        return _selftest()
    if "--probe" in sys.argv:
        return _probe()
    if "--doctor" in sys.argv or "--检查" in sys.argv:
        return _doctor()
    if not _single_instance():
        return 0
    _install_crash_log()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("水印歌词")
    window = App(app)
    app._window = window
    if "--editor" in sys.argv or "--lyrics" in sys.argv:
        QTimer.singleShot(0, window.open_editor)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())

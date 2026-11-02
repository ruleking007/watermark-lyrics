# -*- coding: utf-8 -*-
"""数据层：媒体会话读歌 + 多平台取词 + 本地歌词库"""
import asyncio
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

import requests
from PyQt5.QtCore import QThread, pyqtSignal

from config import ROOT

# 打包成 exe 时 __file__ 指向解包临时目录，歌词库要放在 exe 旁边
APP_DIR = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
           else Path(__file__).resolve().parent)
LYRIC_DIR = APP_DIR / "歌词缓存"          # 可见的歌词库，可直接翻看/删除
LEGACY_DIR = ROOT / "lyrics"              # 旧版哈希缓存，只读兜底

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_CREDIT = re.compile(r"^[\u4e00-\u9fa5A-Za-z ]{1,8}\s*[:：]\s*\S")
_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]')


# ---------------------------------------------------------------- 工具
def _norm(s):
    s = (s or "").lower()
    s = re.sub(r"[\(（\[【].*?[\)）\]】]", "", s)
    s = re.sub(r"[\s\-_·•.,，。!！?？'\"“”‘’/&+]", "", s)
    return s.strip()


def _safe_name(s):
    s = _BAD.sub("_", (s or "").strip())
    return (s[:60] or "未知")


def split_meta(title, artist):
    """有的播放器把"歌名 - 歌手"整串塞进 title，artist 留空"""
    if artist or not title:
        return title, artist
    for sep in (" - ", " – ", " — "):
        if sep in title:
            a, b = title.rsplit(sep, 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    return title, artist


def parse_lrc(text, artist=""):
    """LRC -> [(秒, 文本)]，顺带剔掉制作人名单和"歌名 - 歌手"这类头行"""
    a = _norm(artist)
    rows = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        tags = list(_TIME.finditer(raw))
        if not tags:
            continue
        content = raw[tags[-1].end():].strip()
        if not content:
            continue
        for m in tags:
            mm, ss = int(m.group(1)), int(m.group(2))
            frac = m.group(3) or "0"
            ms = int(frac) * (10 ** (3 - len(frac)))
            rows.append([mm * 60 + ss + ms / 1000.0, content])
    rows.sort(key=lambda r: r[0])
    out = []
    for t, s in rows:
        if t < 6.0 and _CREDIT.match(s):
            continue
        # QQ 的词头常带 "歌名 - 歌手" / "歌名 (《xx》主题曲) - 歌手"
        if t < 10.0 and a and " - " in s and a in _norm(s.split(" - ")[-1]):
            continue
        # 别的平台还有 "歌名(版本)-歌手&合唱者" 这种
        if t < 6.0 and a and a in _norm(s) and len(s) > len(artist) + 2:
            continue
        out.append([t, s])
    return out


def _base_score(title, artist, name, artists):
    n, t = _norm(name), _norm(title)
    if not n or not t:
        return 0.0
    if t == n:
        ns = 1.0
    elif t in n or n in t:
        ns = 0.92
    else:
        ns = difflib.SequenceMatcher(None, t, n).ratio()

    a, ar = _norm(artist), _norm(artists)
    if not a:
        ars = 0.6
    elif a == ar or a in ar or ar in a:
        ars = 1.0
    else:
        ars = difflib.SequenceMatcher(None, a, ar).ratio()
    return ns * 0.62 + ars * 0.38


def _rank(score, dur, ref):
    """时长校正：和参考时长差 12 秒以上视为完全不匹配"""
    if ref and dur:
        close = max(0.0, 1.0 - abs(float(dur) - float(ref)) / 12.0)
        return score * 0.68 + close * 0.32
    return score


# ---------------------------------------------------------------- 歌词库
class LyricStore:
    """歌曲播完后落盘：歌手 - 歌名.json，含歌词、来源、用户对时偏移"""

    def __init__(self, folder=None):
        self.dir = Path(folder) if folder else LYRIC_DIR
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def path(self, title, artist):
        return self.dir / f"{_safe_name(artist)} - {_safe_name(title)}.json"

    def load(self, title, artist):
        p = self.path(title, artist)
        if p.exists():
            try:
                d = json.loads(p.read_text("utf-8"))
                if d.get("lines"):
                    return d
            except Exception:
                pass
        # 旧版哈希缓存兜底
        key = hashlib.sha1(f"{_norm(title)}|{_norm(artist)}".encode()).hexdigest()[:16]
        q = LEGACY_DIR / f"{key}.json"
        if q.exists():
            try:
                d = json.loads(q.read_text("utf-8"))
                if d.get("lines"):
                    return {"source": "netease", "id": d.get("id"), "offset": 0.0,
                            "lines": d["lines"]}
            except Exception:
                pass
        return None

    def save(self, title, artist, record):
        if not title:
            return False
        try:
            self.path(title, artist).write_text(_dump(record), "utf-8")
            return True
        except Exception:
            return False


def _dump(rec):
    """一行一句的 JSON，方便人直接翻看/手改 offset"""
    head = {k: v for k, v in rec.items() if k != "lines"}
    lines = rec.get("lines") or []
    out = ["{"]
    for k, v in head.items():
        out.append('  "%s": %s,' % (k, json.dumps(v, ensure_ascii=False)))
    out.append('  "lines": [')
    for i, (t, s) in enumerate(lines):
        out.append("    [%.2f, %s]%s" % (float(t), json.dumps(s, ensure_ascii=False),
                                        "," if i < len(lines) - 1 else ""))
    out.append("  ]")
    out.append("}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 取词
class LyricService:
    """网易云优先，没有词再切 QQ 音乐；同等相似度下选时长最接近的版本"""

    NETEASE_SEARCH = "https://music.163.com/api/search/get/web"
    NETEASE_LYRIC = "https://music.163.com/api/song/lyric"
    QQ_SEARCH = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
    QQ_LYRIC = "https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"

    def __init__(self):
        self.nt = requests.Session()
        self.nt.headers.update({"User-Agent": UA, "Referer": "https://music.163.com/",
                                "Cookie": "NMTID=00O0000000000000000000000000000000"})
        self.qq = requests.Session()
        self.qq.headers.update({"User-Agent": UA, "Referer": "https://y.qq.com/"})

    # -- 对外
    def resolve(self, title, artist):
        if not title:
            return None
        cands = self._search_netease(title, artist)
        ref = cands[0]["duration"] if cands and cands[0]["base"] >= 0.7 else None
        for c in cands[:3]:
            lines = self._lrc_netease(c["key"], artist)
            if lines:
                return {"source": "netease", "id": c["key"], "duration": c["duration"],
                        "match": round(c["score"], 3), "lines": lines}
        # 网易云没词（或压根没搜到）→ QQ 音乐
        for c in self._search_qq(title, artist, ref)[:2]:
            lines = self._lrc_qq(c["key"], artist)
            if lines:
                return {"source": "qq", "id": c["key"], "duration": c["duration"],
                        "match": round(c["score"], 3), "lines": lines}
        return None

    # -- 网易云
    def _search_netease(self, title, artist):
        try:
            r = self.nt.get(self.NETEASE_SEARCH,
                            params={"s": f"{title} {artist}".strip(), "type": 1,
                                    "offset": 0, "limit": 12}, timeout=8)
            songs = ((r.json() or {}).get("result") or {}).get("songs") or []
        except Exception:
            return []
        out = []
        for s in songs:
            name = s.get("name") or ""
            artists = " ".join(a.get("name", "") for a in (s.get("artists") or []))
            dur = (s.get("duration") or 0) / 1000.0
            base = _base_score(title, artist, name, artists)
            if base < 0.6:
                continue
            out.append({"key": s.get("id"), "name": name, "duration": dur,
                        "base": base, "score": base})
        out.sort(key=lambda c: -c["score"])
        return out

    def _lrc_netease(self, sid, artist):
        try:
            d = self.nt.get(self.NETEASE_LYRIC,
                            params={"id": sid, "lv": -1, "kv": -1, "tv": -1},
                            timeout=8).json()
            return parse_lrc((d.get("lrc") or {}).get("lyric"), artist)
        except Exception:
            return []

    # -- QQ 音乐
    def _search_qq(self, title, artist, ref=None):
        try:
            d = self.qq.get(self.QQ_SEARCH,
                            params={"w": f"{title} {artist}".strip(), "format": "json",
                                    "n": 10, "p": 1, "new_json": 1}, timeout=8).json()
            songs = ((d.get("data") or {}).get("song") or {}).get("list") or []
        except Exception:
            return []
        out = []
        for s in songs:
            name = s.get("name") or ""
            artists = " ".join(x.get("name", "") for x in (s.get("singer") or []))
            dur = s.get("interval") or 0
            base = _base_score(title, artist, name, artists)
            if base < 0.6:
                continue
            out.append({"key": s.get("mid"), "name": name, "duration": dur,
                        "base": base, "score": _rank(base, dur, ref)})
        out.sort(key=lambda c: -c["score"])
        return out

    def _lrc_qq(self, mid, artist):
        if not mid:
            return []
        try:
            r = self.qq.get(self.QQ_LYRIC,
                            params={"songmid": mid, "format": "json",
                                    "nobase64": 1, "g_tk": 5381}, timeout=8)
            txt = r.text.strip()
            if txt.startswith("MusicJsonCallback"):
                txt = txt[txt.index("(") + 1:txt.rindex(")")]
            d = json.loads(txt)
            return parse_lrc(d.get("lyric") or "", artist)
        except Exception:
            return []


# ---------------------------------------------------------------- 媒体会话
class MediaWorker(QThread):
    """后台线程轮询 Windows 媒体会话，读网易云当前播放"""
    track = pyqtSignal(dict)

    def __init__(self, interval=0.6, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._stop = False
        self._last = None

    def stop(self):
        self._stop = True
        self.wait(1500)

    def run(self):
        try:
            asyncio.run(self._loop())
        except Exception:
            self.track.emit({"title": "", "artist": "", "playing": False, "app": ""})

    async def _loop(self):
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager)

        mgr = await Manager.request_async()
        while not self._stop:
            payload = {"title": "", "artist": "", "playing": False, "app": ""}
            try:
                ses = self._pick(mgr)
                if ses is not None:
                    p = await ses.try_get_media_properties_async()
                    info = ses.get_playback_info()
                    payload = {
                        "title": (p.title or "").strip(),
                        "artist": (p.artist or "").strip(),
                        "playing": int(info.playback_status) == 4,  # 4 = Playing
                        "app": (ses.source_app_user_model_id or "").lower(),
                    }
            except Exception:
                pass
            if payload != self._last:
                self._last = payload
                self.track.emit(payload)
            await asyncio.sleep(self.interval)

    @staticmethod
    def _pick(mgr):
        """优先取网易云的会话，没有则退回系统当前会话"""
        try:
            sessions = list(mgr.get_sessions())
        except Exception:
            return mgr.get_current_session()
        fallback = None
        for s in sessions:
            app = (s.source_app_user_model_id or "").lower()
            if "cloudmusic" in app or "netease" in app:
                return s
            if fallback is None:
                fallback = s
        return fallback or mgr.get_current_session()


# ---------------------------------------------------------------- 时间轴
class LyricClock:
    """网易云不上报播放进度，用"切歌归零 + 播放/暂停同步"推算当前时间"""

    def __init__(self):
        import time
        self._time = time
        self._t0 = time.monotonic()
        self.pos = 0.0
        self.offset = 0.0     # 用户对时偏移(秒)，正数=歌词提前
        self.playing = False
        self.lines = []
        self.index = 0
        self.progress = 0.0   # 当前行已唱比例 0-1

    def reset(self):
        self._t0 = self._time.monotonic()
        self.pos = 0.0
        self.index = 0
        self.progress = 0.0

    def tick(self):
        now = self._time.monotonic()
        dt = now - self._t0
        self._t0 = now
        if self.playing and 0.0 <= dt < 3.0:
            self.pos += dt
        if not self.lines:
            self.index = 0
            self.progress = 0.0
            return self.index
        eff = max(0.0, self.pos + self.offset)
        idx = 0
        for i, (t, _) in enumerate(self.lines):
            if t <= eff + 1e-6:
                idx = i
            else:
                break
        self.index = idx
        # 当前行进度：用下一行时间戳当本行结束，最后一行给 4 秒兜底
        t0 = self.lines[idx][0]
        t1 = self.lines[idx + 1][0] if idx + 1 < len(self.lines) else t0 + 4.0
        span = max(0.45, t1 - t0)
        self.progress = min(1.0, max(0.0, (eff - t0) / span))
        return idx

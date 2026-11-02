# -*- coding: utf-8 -*-
"""歌词缓存库：索引、模糊检索、逐句时间微调辅助、原子回写。

文件名规则与 core.LyricStore 一致：<歌手> - <歌名>.json
本模块不依赖界面，方便单独测试或脚本调用。
"""
import difflib
import json
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

from core import LYRIC_DIR, _dump, _safe_name

SOURCE_LABEL = {"netease": "网易云", "qq": "QQ音乐", "local": "本地"}

_BRACKET = re.compile(r"[\(（\[【].*?[\)）\]】]")
_MULTI = re.compile(r"[;；]")
_JUNK = re.compile(r"[\s\-_·•.,，。!！?？'\"“”‘’/&+~、]+")
_NOISE = re.compile(r"[\s_\-]*音乐下载网站[\s\S]*?\.com", re.I)

MIN_SCORE = 0.42          # 搜索命中阈值
BACKUP_DIR = ".备份"       # 改动前的副本放在这个子目录里
KEEP_BACKUPS = 60         # 每个文件夹最多保留的历史版本数


# ---------------------------------------------------------------- 时间
def fmt_time(sec):
    """83.45 -> '01:23.45'"""
    sec = max(0.0, float(sec or 0.0))
    m = int(sec // 60)
    return "%02d:%05.2f" % (m, sec - m * 60)


def parse_time(text):
    """'01:23.45' / '83.45' / '1:23' -> 秒；无法识别时抛 ValueError"""
    t = (text or "").strip().replace("：", ":")
    if not t:
        raise ValueError("空时间")
    if ":" in t:
        parts = t.split(":")
        if len(parts) > 3:
            raise ValueError("时间格式不对")
        sec = float(parts[-1])
        total = 0.0
        for p in parts[:-1]:
            total = total * 60 + (int(p) if p.strip() else 0)
        total = total * 60 + sec
    else:
        total = float(t)
    if total < 0 or total > 6 * 3600:
        raise ValueError("时间超出范围")
    return round(total, 2)


def gap_text(lines, i):
    """第 i 句与上一句的间隔，第一句返回 '—'"""
    if i <= 0:
        return "—"
    return "%+.2f" % (float(lines[i][0]) - float(lines[i - 1][0]))


def is_sorted(lines):
    ts = [float(x[0]) for x in lines]
    return all(ts[i] <= ts[i + 1] + 1e-9 for i in range(len(ts) - 1))


# ---------------------------------------------------------------- 微调
def shift(lines, rows, delta):
    """把指定行的时间整体平移 delta 秒（不小于 0），返回新列表"""
    out = [[round(float(t), 2), s] for t, s in lines]
    for i in rows:
        if 0 <= i < len(out):
            out[i][0] = round(max(0.0, out[i][0] + float(delta)), 2)
    return out


def sort_lines(lines):
    return sorted(([round(float(t), 2), s] for t, s in lines), key=lambda r: r[0])


def scope_rows(rows, count, scope):
    """scope: line=选中行 / from=选中行及其后 / all=全部"""
    rows = [r for r in rows if 0 <= r < count]
    if scope == "all":
        return list(range(count))
    if scope == "from" and rows:
        return list(range(min(rows), count))
    return rows


# ---------------------------------------------------------------- 检索
def clean(s):
    """检索用归一化：去括号内容、去掉分隔符与标点、转小写"""
    s = (s or "").lower()
    s = _BRACKET.sub(" ", s)
    s = _MULTI.sub(" ", s)
    s = _JUNK.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def pretty(s):
    """把播放器塞进来的脏元数据整理成可读值。

    '句号;句号;句号;…' -> '句号'；'菲菲公主 _ 音乐下载网站 yym4.com' -> '菲菲公主'
    """
    s = _NOISE.sub(" ", s or "")
    parts = []
    for p in _MULTI.split(s):
        p = re.sub(r"\s+", " ", p).strip(" -_·•\t")
        if p and p not in parts:
            parts.append(p)
    if not parts:
        return ""
    return "、".join(parts[:3]) + (" 等" if len(parts) > 3 else "")


def _field_score(tok, field):
    if not field or not tok:
        return 0.0
    if field == tok:
        return 1.0
    if field.startswith(tok):
        return 0.94
    if tok in field:
        return 0.88
    words = field.split()
    best_word = max((difflib.SequenceMatcher(None, tok, w).ratio() for w in words), default=0.0)
    whole = difflib.SequenceMatcher(None, tok, field).ratio()
    return max(best_word * 0.74, whole * 0.60)


class Record:
    """一个歌词 JSON 文件的内存视图"""

    def __init__(self, path, data, mtime=None):
        self.path = Path(path)
        self.data = data
        self.title = str(data.get("title") or self.path.stem)
        self.artist = str(data.get("artist") or "")
        self.source = str(data.get("source") or "")
        self.offset = float(data.get("offset") or 0.0)
        self.duration = float(data.get("duration") or 0.0)
        self.lines = data.get("lines") or []
        try:
            self.mtime = self.path.stat().st_mtime if mtime is None else float(mtime)
        except OSError:
            self.mtime = 0.0
        self.score = 0.0
        self.current = False
        self.hay = clean(" ".join(s for _, s in self.lines))

    # -- 展示
    @property
    def disp_title(self):
        return pretty(self.title) or self.path.stem

    @property
    def disp_artist(self):
        return pretty(self.artist)

    @property
    def count(self):
        return len(self.lines)

    @property
    def source_label(self):
        return SOURCE_LABEL.get(self.source, self.source or "未知来源")

    @property
    def stamp(self):
        return time.strftime("%m-%d %H:%M", time.localtime(self.mtime)) if self.mtime else ""

    @property
    def end_time(self):
        return float(self.lines[-1][0]) if self.lines else 0.0

    def label(self):
        return self.disp_title or self.path.stem

    def __repr__(self):
        return "<Record %s %d 句>" % (self.path.name, self.count)


def read_record(path):
    """读一个歌词文件；结构不对时返回 None"""
    p = Path(path)
    try:
        data = json.loads(p.read_text("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    rows = data.get("lines")
    if not isinstance(rows, list) or not rows:
        return None
    norm = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            t = float(row[0])
        except (TypeError, ValueError):
            continue
        norm.append([round(t, 2), str(row[1])])
    if not norm:
        return None
    data["lines"] = norm
    return Record(p, data)


def backup(path):
    """保存前把原文件复制到 .备份/，最多保留最近 KEEP_BACKUPS 份"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        bdir = p.parent / BACKUP_DIR
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = bdir / ("%s.%s.json" % (p.stem, stamp))
        n = 1
        while dst.exists():
            dst = bdir / ("%s.%s-%d.json" % (p.stem, stamp, n))
            n += 1
        shutil.copy2(str(p), str(dst))
        files = sorted(bdir.glob("*.json"),
                       key=lambda f: f.stat().st_mtime if f.exists() else 0, reverse=True)
        for old in files[KEEP_BACKUPS:]:
            try:
                old.unlink()
            except OSError:
                pass
        return dst
    except OSError:
        return None


def save_record(path, data, backup_copy=True):
    """先写临时文件再替换，避免中途崩溃留下半个 JSON。

    内容与磁盘上一致时直接返回，不重复写、也不产生多余的备份。
    """
    p = Path(path)
    text = _dump(data)
    if p.exists():
        try:
            if p.read_text("utf-8") == text:
                return True
        except (OSError, UnicodeDecodeError):
            pass
        if backup_copy:
            backup(p)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".lyric-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, p)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
    except Exception:
        return False


class Library:
    """歌词缓存文件夹的索引，可按歌名/歌手/歌词片段检索"""

    def __init__(self, folder=None):
        self.folder = Path(folder) if folder else Path(LYRIC_DIR)
        self.items = []
        self.bad_files = []
        self.reload()

    # -- 索引
    def reload(self):
        self.items = []
        self.bad_files = []
        try:
            files = sorted(self.folder.glob("*.json"))
        except OSError:
            files = []
        for p in files:
            rec = read_record(p)
            if rec is not None:
                self.items.append(rec)
            else:
                self.bad_files.append(p)
        return len(self.items)

    def reload_one(self, path):
        rec = read_record(path)
        if rec is None:
            return None
        target = Path(path)
        for i, old in enumerate(self.items):
            if old.path == target:
                self.items[i] = rec
                return rec
        self.items.append(rec)
        return rec

    @property
    def total_lines(self):
        return sum(r.count for r in self.items)

    # -- 路径
    def target_path(self, title, artist):
        return self.folder / ("%s - %s.json" % (_safe_name(artist), _safe_name(title)))

    # -- 检索
    @staticmethod
    def _score(tokens, rec):
        title = clean(rec.disp_title)
        artist = clean(rec.disp_artist)
        fname = clean(rec.path.stem)
        per = []
        for tok in tokens:
            per.append(max(_field_score(tok, title),
                           _field_score(tok, fname) * 0.96,
                           _field_score(tok, artist) * 0.82,
                           (0.62 if tok in rec.hay else 0.0)))
        if not per:
            return 0.0
        return min(per) * 0.74 + (sum(per) / len(per)) * 0.26

    def search(self, query, now_title="", now_artist="", limit=300):
        tokens = clean(query).split()
        now_key = (clean(now_title), clean(now_artist))
        now_path = self.target_path(now_title, now_artist) if now_title else None
        out = []
        for rec in self.items:
            rec.current = bool(now_title) and (
                (clean(rec.disp_title), clean(rec.disp_artist)) == now_key or rec.path == now_path)
            rec.score = 0.0
            if not tokens:
                out.append(rec)
                continue
            s = self._score(tokens, rec)
            if s >= MIN_SCORE:
                if rec.current:
                    s = min(1.0, s + 0.05)
                rec.score = round(s, 4)
                out.append(rec)
        if tokens:
            out.sort(key=lambda r: (-r.score, -r.current, -r.mtime))
        else:
            out.sort(key=lambda r: (-r.current, -r.mtime))
        return out[:limit]

    # -- 写入
    @staticmethod
    def build_data(rec, lines, title=None, artist=None, offset=None):
        """在保留原有字段和顺序的前提下生成待写入的数据"""
        data = dict(rec.data)
        data["lines"] = [[round(max(0.0, float(t)), 2), str(s)] for t, s in lines]
        if title is not None:
            data["title"] = title
        if artist is not None:
            data["artist"] = artist
        data["offset"] = round(float(rec.offset if offset is None else offset), 2)
        data["saved_at"] = time.strftime("%Y-%m-%d %H:%M")
        return data

    def save(self, rec, lines, title=None, artist=None, offset=None):
        data = self.build_data(rec, lines, title=title, artist=artist, offset=offset)
        if not save_record(rec.path, data):
            return None
        new = self.reload_one(rec.path)
        return new or rec

    def remove(self, rec):
        try:
            rec.path.unlink()
            return True
        except OSError:
            return False


# ---------------------------------------------------------------- 自检
def _selftest():
    import shutil
    src = Path(LYRIC_DIR)
    tmp = Path(tempfile.mkdtemp(prefix="lyriclib-"))
    for p in src.glob("*.json"):
        shutil.copy2(p, tmp / p.name)

    lib = Library(tmp)
    assert lib.items, "索引为空"
    print("索引 %d 个文件 / %d 句" % (len(lib.items), lib.total_lines))

    for q in ("流星雨", "流星", "F4", "周杰伦 花海", "句号", "如果可以"):
        hits = lib.search(q)
        print("搜索 %-10s -> %2d 个候选  首选：%s · %s (%s)"
              % (q, len(hits), hits[0].disp_title if hits else "-",
                 hits[0].disp_artist if hits else "-",
                 "%.2f" % hits[0].score if hits else ""))

    rec = lib.search("流星雨")[0]
    lines = [[float(t), s] for t, s in rec.lines]
    before = lines[3][0]
    lines2 = shift(lines, [3], -0.5)
    assert abs(lines2[3][0] - (before - 0.5)) < 0.011, lines2[3]
    lines3 = shift(lines2, [3], 0.5)
    assert abs(lines3[3][0] - before) < 0.011
    assert parse_time(fmt_time(83.45)) == 83.45
    assert parse_time("1:23") == 83.0 and parse_time("83") == 83.0
    assert gap_text(lines, 0) == "—"

    data = Library.build_data(rec, lines2, offset=0.0)
    out = tmp / "edit-check.json"
    assert save_record(out, data)
    back = read_record(out)
    assert back is not None and back.count == rec.count
    assert abs(float(back.lines[3][0]) - lines2[3][0]) < 0.005
    assert back.data.get("title") == rec.title
    print("回写校验通过：", out.name, back.count, "句")

    shutil.rmtree(tmp, ignore_errors=True)
    print("lyriclib selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
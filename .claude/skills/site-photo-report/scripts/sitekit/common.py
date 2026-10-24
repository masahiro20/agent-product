"""共通ユーティリティ（フォント・JSON読込・単位変換）。"""
import json
import os

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(SKILL_DIR, "data")

FONT = "JP"
REPO_DIR = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))
_FONT_CANDIDATES = [
    os.environ.get("SITEKIT_FONT", ""),
    os.path.join(REPO_DIR, "fonts", "ipag.ttf"),
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]
_font_ready = False


def font_path():
    for p in _FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise RuntimeError("日本語フォントが見つかりません（IPAゴシック等をインストールしてください）")


def ensure_font():
    global _font_ready
    if not _font_ready:
        pdfmetrics.registerFont(TTFont(FONT, font_path()))
        _font_ready = True
    return FONT


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_data(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return None
    return load_json(path)


def yen(v):
    if v is None:
        return "-"
    return f"{int(round(v)):,}"


def man_yen(v):
    """円 → 「123.4万円」表記。"""
    if v is None:
        return "-"
    return f"{v / 10000:,.1f}万円"


def tsubo(m2):
    return m2 / 3.30579


MM = mm

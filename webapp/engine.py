"""スキル（.claude/skills/site-photo-report）の計算・作図エンジンを Web アプリから使うための入口。"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "site-photo-report", "scripts")

# サーバーレス環境では書き込めるのは /tmp だけ
os.environ.setdefault("SITE_DATA_CACHE", "/tmp/site_public_data")
os.environ.setdefault("SITEKIT_FONT", os.path.join(ROOT, "fonts", "ipag.ttf"))

if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import public_data  # noqa: E402,F401
from sitekit import demolition, elevation, grading, report, terrain  # noqa: E402,F401
from sitekit.common import load_data  # noqa: E402,F401

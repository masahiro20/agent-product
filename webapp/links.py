"""期限付きのダウンロードリンク（MCP の回答に載せる。アクセスキー無しで開けるが、署名と期限で守る）。"""
import hashlib
import hmac
import os
import time
import urllib.parse

TTL_SEC = 7 * 24 * 3600


def _key():
    # 新しい秘密を増やさないよう、既存の秘密から用途別の鍵を作る
    base = (os.environ.get("ACCESS_PASSWORD", "") + "|" + os.environ.get("BLOB_READ_WRITE_TOKEN", "")).encode()
    return hashlib.sha256(b"genchi-links|" + base).digest()


def _sig(case_id, fmt, exp, extra):
    msg = f"{case_id}|{fmt}|{exp}|{extra}".encode()
    return hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:32]


def file_url(base, case_id, fmt, **params):
    """params は見積依頼書の kind・due・contact など（署名に含める）。"""
    exp = int(time.time()) + TTL_SEC
    extra = urllib.parse.urlencode(sorted((k, v) for k, v in params.items() if v))
    q = {"exp": exp, "sig": _sig(case_id, fmt, exp, extra)}
    q.update({k: v for k, v in params.items() if v})
    return f"{base}/files/{case_id}/{fmt}?" + urllib.parse.urlencode(q)


def verify(case_id, fmt, query):
    try:
        exp = int(query.get("exp", "0"))
    except ValueError:
        return False
    if exp < time.time():
        return False
    extra = urllib.parse.urlencode(sorted((k, v) for k, v in query.items() if k not in ("exp", "sig") and v))
    return hmac.compare_digest(query.get("sig", ""), _sig(case_id, fmt, exp, extra))

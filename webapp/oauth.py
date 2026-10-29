"""MCP コネクタ用の OAuth（claude.ai → このサーバー → Google ログイン）。

claude.ai のコネクタは MCP の認可仕様どおり、このサーバーを OAuth の認可サーバーとして扱う
（動的クライアント登録 → /oauth/authorize → /oauth/token）。ログイン自体は Google に任せ、
Google のリフレッシュトークンを暗号化してこちらのトークンに入れる（サーバー側に保存しない）。

環境変数:
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  Google Cloud の OAuth クライアント（ウェブアプリ）
  ALLOWED_GOOGLE_EMAILS                    使ってよい Google アカウント（カンマ区切り。"@example.co.jp" でドメイン指定）。
                                           未設定なら誰も使えない
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = "openid email https://www.googleapis.com/auth/drive.readonly"
CLAUDE_REDIRECT_HOSTS = {"claude.ai", "claude.com"}  # コネクタの戻り先（https://claude.ai/api/mcp/auth_callback 等）
ACCESS_TTL = 3600
CODE_TTL = 300


def configured():
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _fernet():
    base = (os.environ.get("GOOGLE_CLIENT_SECRET", "") + "|" + os.environ.get("ACCESS_PASSWORD", "")).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"genchi-oauth|" + base).digest()))


def seal(obj):
    return _fernet().encrypt(json.dumps(obj, separators=(",", ":")).encode()).decode()


def unseal(token, kind):
    try:
        obj = json.loads(_fernet().decrypt(token.encode()))
    except (InvalidToken, ValueError):
        return None
    if obj.get("t") != kind or obj.get("exp", 1e18) < time.time():
        return None
    return obj


def email_allowed(email):
    email = (email or "").lower()
    rules = [r.strip().lower() for r in os.environ.get("ALLOWED_GOOGLE_EMAILS", "").split(",") if r.strip()]
    return any(email == r or (r.startswith("@") and email.endswith(r)) for r in rules)


def redirect_ok(uri):
    p = urllib.parse.urlparse(uri or "")
    if p.scheme == "https" and p.hostname in CLAUDE_REDIRECT_HOSTS:
        return True
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1")  # 動作確認用


def _post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ------------------------------------------------------------------ メタデータ

def protected_resource(base):
    return {"resource": f"{base}/mcp", "authorization_servers": [base], "bearer_methods_supported": ["header"],
            "scopes_supported": ["cases"], "resource_name": "現地写真レポート"}


def authorization_server(base):
    return {"issuer": base, "authorization_endpoint": f"{base}/oauth/authorize", "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "scopes_supported": ["cases"]}


def register(body):
    """動的クライアント登録。クライアント情報は保存せず、戻り先 URL だけ確かめる。"""
    uris = body.get("redirect_uris") or []
    if not uris or not all(redirect_ok(u) for u in uris):
        raise ValueError("redirect_uris が許可されていません")
    return {"client_id": "genchi-" + secrets.token_urlsafe(12), "client_id_issued_at": int(time.time()),
            "redirect_uris": uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "client_name": body.get("client_name", "")}


# ------------------------------------------------------------------ 認可（Google ログインへ）

def authorize_url(base, q):
    """claude.ai からの /oauth/authorize を Google のログイン画面へつなぐ URL。"""
    if q.get("response_type") != "code":
        raise ValueError("response_type=code だけに対応しています")
    if not redirect_ok(q.get("redirect_uri")):
        raise ValueError("redirect_uri が許可されていません")
    if not q.get("code_challenge") or q.get("code_challenge_method", "S256") != "S256":
        raise ValueError("PKCE（S256）が必要です")
    state = seal({"t": "st", "exp": time.time() + 900, "redirect_uri": q["redirect_uri"], "state": q.get("state", ""),
                  "cc": q["code_challenge"], "client_id": q.get("client_id", "")})
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": f"{base}/oauth/google/callback",
        "response_type": "code", "scope": GOOGLE_SCOPES, "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state})


def google_callback(base, q):
    """Google から戻ってきたら、許可されたアカウントか確かめて claude.ai へ認可コードを返す。戻り値は戻り先 URL。"""
    st = unseal(q.get("state", ""), "st")
    if not st:
        raise ValueError("ログインの有効期限が切れました。もう一度コネクタを接続してください。")
    if q.get("error"):
        return st["redirect_uri"] + "?" + urllib.parse.urlencode({"error": "access_denied", "state": st["state"]})
    tok = _post_form(GOOGLE_TOKEN, {"code": q.get("code", ""), "client_id": os.environ["GOOGLE_CLIENT_ID"],
                                    "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                                    "redirect_uri": f"{base}/oauth/google/callback", "grant_type": "authorization_code"})
    email = _id_token_email(tok.get("id_token", ""))
    if not email_allowed(email):
        raise PermissionError(f"{email or 'このアカウント'} は使用を許可されていません。管理者に ALLOWED_GOOGLE_EMAILS への追加を依頼してください。")
    if not tok.get("refresh_token"):
        raise ValueError("Google からリフレッシュトークンを受け取れませんでした。Google アカウントの「サードパーティ アクセス」から一度連携を解除して、もう一度接続してください。")
    code = seal({"t": "code", "exp": time.time() + CODE_TTL, "grt": tok["refresh_token"], "email": email,
                 "cc": st["cc"], "redirect_uri": st["redirect_uri"]})
    return st["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": st["state"]})


def _id_token_email(id_token):
    # Google のトークン窓口から TLS で直接受け取った id_token なので、署名の検証は省いて中身だけ読む
    try:
        payload = id_token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data.get("email") if data.get("email_verified", True) else None
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ トークン

def token(form):
    gt = form.get("grant_type")
    if gt == "authorization_code":
        c = unseal(form.get("code", ""), "code")
        if not c or c["redirect_uri"] != form.get("redirect_uri"):
            raise ValueError("invalid_grant")
        verifier = form.get("code_verifier", "")
        cc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        if cc != c["cc"]:
            raise ValueError("invalid_grant")
        grt, email = c["grt"], c["email"]
    elif gt == "refresh_token":
        r = unseal(form.get("refresh_token", ""), "rt")
        if not r or not email_allowed(r["email"]):
            raise ValueError("invalid_grant")
        grt, email = r["grt"], r["email"]
    else:
        raise ValueError("unsupported_grant_type")
    return {"access_token": seal({"t": "at", "exp": time.time() + ACCESS_TTL, "grt": grt, "email": email}),
            "token_type": "Bearer", "expires_in": ACCESS_TTL, "scope": "cases",
            "refresh_token": seal({"t": "rt", "grt": grt, "email": email})}


_google_cache = {}


def user_from_bearer(header):
    """Authorization ヘッダーから利用者（email と Google のアクセストークンを取る関数）を返す。無効なら None。"""
    if not (header or "").startswith("Bearer "):
        return None
    at = unseal(header[7:].strip(), "at")
    if not at or not email_allowed(at["email"]):
        return None
    grt = at["grt"]

    def google_token():
        key = hashlib.sha256(grt.encode()).hexdigest()
        hit = _google_cache.get(key)
        if hit and hit[1] > time.time() + 60:
            return hit[0]
        r = _post_form(GOOGLE_TOKEN, {"client_id": os.environ["GOOGLE_CLIENT_ID"],
                                      "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                                      "refresh_token": grt, "grant_type": "refresh_token"})
        _google_cache[key] = (r["access_token"], time.time() + int(r.get("expires_in", 3000)))
        return r["access_token"]

    return {"email": at["email"], "google_token": google_token}

"""网站账号：登录 qushuiyin.asia，读取会员等级。"""
import base64, hashlib, json
import httpx

SITE = "https://qushuiyin.asia"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Dingbo"

# 每个等级的限制：rooms=同时检测的直播间数，rec=同时录制数，hours=单场录制上限（0=不限）
LIMITS = {
    "guest": {"rooms": 0, "rec": 0, "hours": 2},
    "free": {"rooms": 3, "rec": 1, "hours": 2},
    "plus": {"rooms": 20, "rec": 3, "hours": 0},
    "pro": {"rooms": 100, "rec": 10, "hours": 0},
    "admin": {"rooms": 9999, "rec": 9999, "hours": 0},
}
PLAN_NAME = {"guest": "未登录", "free": "免费版", "plus": "Plus 会员", "pro": "Pro 会员", "admin": "管理员"}


def password_hash(email: str, password: str) -> str:
    """与网页端 window.vgPh 一致：PBKDF2-SHA256 20 万次，盐 qushuiyin|小写邮箱。"""
    salt = ("qushuiyin|" + email.strip().lower()).encode()
    return base64.b64encode(hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000, 32)).decode()


class Account:
    def __init__(self, store):
        self.store = store  # dict-like persisted config
        self.user = None

    def _client(self):
        h = {"User-Agent": UA, "Accept": "application/json"}
        tok = self.store.get("token")
        if tok:
            h["Authorization"] = "Bearer " + tok
        return httpx.Client(base_url=SITE, headers=h, timeout=20, follow_redirects=True)

    def login(self, email: str, password: str) -> dict:
        body = {"email": email.strip(), "password": password, "ph": password_hash(email, password)}
        with self._client() as c:
            r = c.post("/api/auth/login", json=body)
            try:
                j = r.json()
            except Exception:
                return {"ok": False, "error": f"服务器返回 {r.status_code}，请稍后再试"}
        if j.get("token"):
            self.store["token"] = j["token"]
            self.store["email"] = j.get("email") or email
            self.user = j
            return {"ok": True}
        return {"ok": False, "error": j.get("error") or "登录失败"}

    def refresh(self) -> dict | None:
        if not self.store.get("token"):
            self.user = None
            return None
        try:
            with self._client() as c:
                j = c.get("/api/auth/me").json()
        except Exception:
            return self.user  # 网络问题时沿用上次结果
        if j.get("email"):
            self.user = j
        else:
            self.user = None
            self.store.pop("token", None)
        return self.user

    def logout(self):
        self.store.pop("token", None)
        self.user = None

    @property
    def plan(self) -> str:
        if not self.user:
            return "guest"
        p = self.user.get("plan") or "free"
        return p if p in LIMITS else "free"

    @property
    def limits(self) -> dict:
        return LIMITS[self.plan]

    def latest_version(self) -> dict | None:
        try:
            with self._client() as c:
                return c.get("/api/client/version").json()
        except Exception:
            return None

"""视频下载：调网站 /api/parse 解析（额度与网站共用），文件直接从平台 CDN 下到本地。"""
import re, threading, time, uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from .account import SITE, UA

IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
URL_RE = re.compile(r"https?://[^\s，。！？、\"'<>）)】]+")


def safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t#]+', "_", s or "").strip()[:50] or "未命名"


def media_headers(url: str) -> dict:
    h = httpx.URL(url).host
    if re.search(r"bilivideo|akamaized|hdslb|bilibili", h):
        return {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    if re.search(r"xhscdn|rednotecdn|xiaohongshu", h):
        return {"User-Agent": UA, "Referer": "https://www.xiaohongshu.com/"}
    return {"User-Agent": IOS_UA}


def split_links(text: str) -> list[str]:
    """一行一条；一行里有链接就取链接，没有就整行（分享口令）。"""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        urls = URL_RE.findall(line)
        out.extend(urls if len(urls) > 1 else [line])
    return out[:20]


class Job:
    def __init__(self, text: str):
        self.id = uuid.uuid4().hex[:10]
        self.text = text
        self.status = "排队中"  # 排队中/解析中/下载中/完成/失败
        self.error = ""
        self.title = ""
        self.author = ""
        self.platform = ""
        self.cover = ""
        self.duration = 0
        self.kind = ""  # video / images
        self.done = 0
        self.total = 0
        self.files: list[str] = []
        self.folder = ""
        self.t = time.time()

    def view(self):
        return {k: getattr(self, k) for k in ("id", "text", "status", "error", "title", "author", "platform", "cover",
                                              "duration", "kind", "done", "total", "files", "folder", "t")}


class Downloader:
    def __init__(self, manager):
        self.m = manager
        self.jobs: list[Job] = []
        self.quota = None
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(2)

    def state(self):
        with self.lock:
            return {"jobs": [j.view() for j in reversed(self.jobs[-50:])], "quota": self.quota}

    def add(self, text: str) -> dict:
        links = split_links(text)
        if not links:
            return {"ok": False, "error": "请粘贴抖音、小红书或 B站的分享链接"}
        with self.lock:
            for s in links:
                j = Job(s)
                self.jobs.append(j)
                threading.Thread(target=self._run, args=(j,), daemon=True).start()
        return {"ok": True, "msg": f"已添加 {len(links)} 条，正在解析"}

    def clear(self):
        with self.lock:
            self.jobs = [j for j in self.jobs if j.status in ("排队中", "解析中", "下载中")]
        return {"ok": True}

    # ---- 内部 ----
    def _api(self):
        h = {"User-Agent": UA, "Accept": "application/json"}
        tok = self.m.account.store.get("token")
        if tok:
            h["Authorization"] = "Bearer " + tok
        return httpx.Client(base_url=SITE, headers=h, timeout=40, follow_redirects=True)

    def _run(self, j: Job):
        with self.sem:
            try:
                j.status = "解析中"
                with self._api() as c:
                    r = c.post("/api/parse", json={"url": j.text})
                    try:
                        res = r.json()
                    except Exception:
                        raise RuntimeError(f"网站返回 {r.status_code}，请稍后再试")
                if res.get("quota"):
                    self.quota = res["quota"]
                if not res.get("ok"):
                    if res.get("code") == "quota" and res.get("quota"):
                        self.quota = res["quota"]
                    raise RuntimeError(res.get("error") or "解析失败")
                d = res.get("data") or {}
                j.title, j.author, j.platform = d.get("title") or "", d.get("author") or "", d.get("platform") or ""
                j.cover, j.duration = d.get("cover") or "", d.get("duration") or 0
                folder = Path(self.m.cfg["saveDir"]) / "视频下载"
                folder.mkdir(parents=True, exist_ok=True)
                j.folder = str(folder)
                base = safe(f"{j.author}_{j.title}" if j.author else j.title or j.platform)
                items = []
                if d.get("video"):
                    j.kind = "video"
                    items.append((d["video"], folder / f"{base}.mp4"))
                else:
                    imgs = [x.get("url") if isinstance(x, dict) else x for x in (d.get("images") or [])]
                    imgs = [x for x in imgs if x]
                    if not imgs:
                        raise RuntimeError("没有找到可下载的视频或图片")
                    j.kind = "images"
                    sub = folder / base
                    sub.mkdir(exist_ok=True)
                    j.folder = str(sub)
                    for i, u in enumerate(imgs, 1):
                        ext = ".png" if ".png" in u.split("?")[0] else (".webp" if "webp" in u else ".jpg")
                        items.append((u, sub / f"{i:02d}{ext}"))
                j.status = "下载中"
                j.total = len(items)
                for u, p in items:
                    p = self._unique(p)
                    self._fetch(u, p, res.get("dlt") or "")
                    j.files.append(str(p))
                    j.done += 1
                j.status = "完成"
                self.m.log(f"[下载] 完成：{j.title or j.text[:30]}（{j.done} 个文件）")
            except Exception as e:
                j.status = "失败"
                j.error = str(e)[:200]
                self.m.log(f"[下载] 失败：{j.text[:40]} → {j.error}")

    @staticmethod
    def _unique(p: Path) -> Path:
        if not p.exists():
            return p
        for i in range(2, 999):
            q = p.with_name(f"{p.stem}({i}){p.suffix}")
            if not q.exists():
                return q
        return p

    def _fetch(self, url: str, path: Path, dlt: str):
        """先从平台 CDN 直连；失败再走网站中转。"""
        tmp = path.with_suffix(path.suffix + ".part")
        tries = [(url, media_headers(url))]
        tok = self.m.account.store.get("token") or ""
        proxied = f"{SITE}/api/proxy?u={quote(url, safe='')}" + (f"&t={quote(dlt, safe='')}" if dlt else "")
        tries.append((proxied, {"User-Agent": UA, "Authorization": "Bearer " + tok}))
        err = None
        for u, h in tries:
            try:
                with httpx.stream("GET", u, headers=h, timeout=60, follow_redirects=True) as r:
                    if r.status_code >= 400:
                        raise RuntimeError(f"下载失败（{r.status_code}）")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_bytes(256 * 1024):
                            f.write(chunk)
                if tmp.stat().st_size < 1024:
                    raise RuntimeError("文件太小，可能链接已失效")
                tmp.replace(path)
                return
            except Exception as e:
                err = e
                tmp.unlink(missing_ok=True)
        raise RuntimeError(str(err) or "下载失败")

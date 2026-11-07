"""监控与录制核心：循环检测开播 → ffmpeg 录制 → 转 mp4。"""
import asyncio, json, os, random, re, shutil, subprocess, sys, threading, time, uuid
from datetime import datetime
from pathlib import Path

import streamget

from .account import Account, PLAN_NAME
from .platforms import HEADERS, detect, extract_urls

APPDIR = Path(os.environ.get("APPDATA") or (Path.home() / ".config")) / "Dingbo"
APPDIR.mkdir(parents=True, exist_ok=True)
CFG = APPDIR / "config.json"
QUALITIES = {"OD": "原画", "UHD": "超清", "HD": "高清", "SD": "标清", "LD": "流畅"}
REC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
NOWIN = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


def ffmpeg_path() -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (base / "ffmpeg" / "ffmpeg.exe", base / "ffmpeg.exe", Path(sys.executable).parent / "ffmpeg.exe"):
        if p.exists():
            return str(p)
    return shutil.which("ffmpeg") or "ffmpeg"


def safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s or "").strip()[:40] or "未命名"


class Room:
    def __init__(self, d: dict):
        self.id = d.get("id") or uuid.uuid4().hex[:10]
        self.url = d["url"]
        self.platform = d.get("platform", "")
        self.name = d.get("name", "")
        self.quality = d.get("quality", "OD")
        self.enabled = d.get("enabled", True)
        # 运行态
        self.status = "等待检测"  # 等待检测/检测中/未开播/直播中/录制中/出错/已暂停/已达上限
        self.title = ""
        self.live = False
        self.last_check = 0.0
        self.error = ""
        self.proc: subprocess.Popen | None = None
        self.file: Path | None = None
        self.rec_start = 0.0
        self.session_secs = 0.0  # 本场已录秒数（免费版限时用）
        self.capped = False

    def save(self):
        return {"id": self.id, "url": self.url, "platform": self.platform, "name": self.name,
                "quality": self.quality, "enabled": self.enabled}

    def view(self):
        rec = self.proc is not None
        size = self.file.stat().st_size if (rec and self.file and self.file.exists()) else 0
        return {"id": self.id, "url": self.url, "platform": self.platform, "name": self.name or "（检测后显示）",
                "quality": self.quality, "qualityName": QUALITIES.get(self.quality, self.quality),
                "enabled": self.enabled, "status": self.status, "title": self.title, "live": self.live,
                "error": self.error, "recording": rec,
                "elapsed": int(time.time() - self.rec_start) if rec else 0, "size": size,
                "lastCheck": self.last_check}


class Manager:
    def __init__(self):
        self.cfg = self._load()
        self.cfg.setdefault("interval", 60)
        self.cfg.setdefault("saveDir", str(Path.home() / "Videos" / "盯播录制"))
        self.cfg.setdefault("toMp4", True)
        self.cfg.setdefault("segmentMin", 0)  # 0=不分段
        self.account = Account(self.cfg)
        self.rooms: list[Room] = [Room(r) for r in self.cfg.get("rooms", [])]
        self.logs: list[str] = []
        self.files: list[dict] = self.cfg.get("files", [])[-200:]
        self.lock = threading.RLock()
        self.loop = asyncio.new_event_loop()
        self._wake = None
        self.notify = lambda title, msg: None  # 由界面层替换
        threading.Thread(target=self._run, daemon=True).start()

    # ---------- 配置 ----------
    def _load(self) -> dict:
        try:
            return json.loads(CFG.read_text("utf-8"))
        except Exception:
            return {}

    def persist(self):
        with self.lock:
            self.cfg["rooms"] = [r.save() for r in self.rooms]
            self.cfg["files"] = self.files[-200:]
            tmp = CFG.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(CFG)

    def log(self, msg: str):
        line = datetime.now().strftime("%H:%M:%S ") + msg
        with self.lock:
            self.logs.append(line)
            self.logs = self.logs[-300:]
        try:
            with open(APPDIR / "dingbo.log", "a", encoding="utf-8") as f:
                f.write(datetime.now().strftime("%Y-%m-%d ") + line + "\n")
        except Exception:
            pass

    # ---------- 对外操作 ----------
    def add_rooms(self, text: str, quality: str = "OD") -> dict:
        urls = extract_urls(text)
        if not urls:
            return {"ok": False, "error": "没有识别到链接，请粘贴直播间地址或分享链接"}
        lim = self.account.limits
        added, bad, full = 0, [], 0
        with self.lock:
            have = {r.url for r in self.rooms}
            for u in urls:
                if u in have:
                    continue
                d = detect(u)
                if not d:
                    bad.append(u)
                    continue
                if len(self.rooms) >= lim["rooms"]:
                    full += 1
                    continue
                self.rooms.append(Room({"url": u, "platform": d[0], "quality": quality}))
                have.add(u)
                added += 1
        self.persist()
        self.kick()
        msg = f"已添加 {added} 个直播间"
        if bad:
            msg += f"，{len(bad)} 个链接暂不支持"
        if full:
            msg += f"，{full} 个超出{PLAN_NAME[self.account.plan]}上限（{lim['rooms']} 个）"
        return {"ok": added > 0, "msg": msg, "error": "" if added else msg}

    def update_room(self, rid: str, patch: dict):
        with self.lock:
            r = self._room(rid)
            if not r:
                return {"ok": False}
            if "quality" in patch and patch["quality"] in QUALITIES:
                r.quality = patch["quality"]
            if "name" in patch:
                r.name = str(patch["name"])[:40]
            if "enabled" in patch:
                r.enabled = bool(patch["enabled"])
                if not r.enabled:
                    self._stop(r, "已暂停")
                    r.status = "已暂停"
                else:
                    r.status = "等待检测"
                    r.last_check = 0
        self.persist()
        self.kick()
        return {"ok": True}

    def remove_room(self, rid: str):
        with self.lock:
            r = self._room(rid)
            if r:
                self._stop(r, "已删除")
                self.rooms.remove(r)
        self.persist()
        return {"ok": True}

    def stop_room(self, rid: str):
        with self.lock:
            r = self._room(rid)
            if r and r.proc:
                r.capped = True  # 手动停止后本场不再自动续录
                self._stop(r, "手动停止")
                r.status = "直播中（已手动停止）"
        return {"ok": True}

    def check_now(self):
        with self.lock:
            for r in self.rooms:
                r.last_check = 0
        self.kick()
        return {"ok": True}

    def set_settings(self, s: dict):
        if "interval" in s:
            self.cfg["interval"] = max(30, min(600, int(s["interval"])))
        if "saveDir" in s and s["saveDir"]:
            self.cfg["saveDir"] = s["saveDir"]
        if "toMp4" in s:
            self.cfg["toMp4"] = bool(s["toMp4"])
        if "segmentMin" in s:
            self.cfg["segmentMin"] = max(0, min(240, int(s["segmentMin"])))
        self.persist()
        return {"ok": True}

    def state(self) -> dict:
        a = self.account
        with self.lock:
            return {
                "user": {"email": (a.user or {}).get("email", ""), "plan": a.plan, "planName": PLAN_NAME[a.plan],
                          "vipUntil": (a.user or {}).get("vipUntil", 0)},
                "limits": a.limits,
                "rooms": [r.view() for r in self.rooms],
                "recording": sum(1 for r in self.rooms if r.proc),
                "logs": self.logs[-80:],
                "files": list(reversed(self.files[-50:])),
                "settings": {k: self.cfg[k] for k in ("interval", "saveDir", "toMp4", "segmentMin")},
                "qualities": QUALITIES,
            }

    def shutdown(self):
        with self.lock:
            for r in self.rooms:
                self._stop(r, "退出程序")
        self.persist()

    # ---------- 内部 ----------
    def _room(self, rid):
        return next((r for r in self.rooms if r.id == rid), None)

    def kick(self):
        if self._wake:
            self.loop.call_soon_threadsafe(self._wake.set)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._main())

    async def _main(self):
        self._wake = asyncio.Event()
        self.log("盯播已启动")
        await asyncio.to_thread(self.account.refresh)
        last_me = time.time()
        sem = asyncio.Semaphore(3)
        while True:
            if time.time() - last_me > 1800:  # 每 30 分钟刷新一次会员状态
                await asyncio.to_thread(self.account.refresh)
                last_me = time.time()
            self._reap()
            lim = self.account.limits
            iv = self.cfg["interval"]
            with self.lock:
                active = [r for r in self.rooms if r.enabled][: lim["rooms"]]
                for r in self.rooms:
                    if r.enabled and r not in active and not r.proc:
                        r.status = "超出套餐上限"
                due = [r for r in active if not r.proc and time.time() - r.last_check >= iv]
            async def one(r):
                async with sem:
                    await self._check(r)
                    await asyncio.sleep(random.uniform(0.5, 1.5))
            if due:
                await asyncio.gather(*(one(r) for r in due))
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass

    async def _check(self, r: Room):
        r.last_check = time.time()
        if r.status in ("等待检测", "出错"):
            r.status = "检测中"
        d = detect(r.url)
        if not d:
            r.status, r.error = "出错", "不支持的链接"
            return
        name, cls_name, how = d
        try:
            s = getattr(streamget, cls_name)()
            fns = [how, "web" if how == "app" else "app"]
            data, err = None, RuntimeError("获取直播信息失败")
            for f in fns:
                fn = getattr(s, f"fetch_{f}_stream_data", None)
                if not fn:
                    continue
                try:
                    data = await asyncio.wait_for(fn(r.url), 30)
                    if data:
                        break
                except Exception as e:
                    err = e
            if not data:
                raise err
            info = await asyncio.wait_for(s.fetch_stream_url(data, r.quality), 30)
        except Exception as e:
            r.status, r.error = "出错", (str(e) or type(e).__name__)[:120]
            self.log(f"[{r.name or r.url}] 检测失败：{r.error}")
            return
        r.error = ""
        if info.anchor_name and not r.name:
            r.name = safe(info.anchor_name)
            self.persist()
        was_live = r.live
        r.live = bool(info.is_live)
        r.title = info.title or ""
        if not r.live:
            if was_live:
                self.log(f"[{r.name}] 已下播")
            r.status, r.session_secs, r.capped = "未开播", 0, False
            return
        if not was_live:
            self.log(f"[{r.name}] 开播了：{r.title}")
            self.notify("开播提醒", f"{r.name} 开播了")
        url = info.record_url or info.flv_url or info.m3u8_url
        lim = self.account.limits
        if r.capped:
            r.status = "直播中（本场已达录制上限）" if lim["hours"] else "直播中（已手动停止）"
            return
        with self.lock:
            busy = sum(1 for x in self.rooms if x.proc)
        if busy >= lim["rec"]:
            r.status = f"直播中（同时录制已满 {lim['rec']} 个）"
            return
        if not url:
            r.status, r.error = "出错", "没拿到直播流地址"
            return
        self._start(r, url, name)

    def _start(self, r: Room, url: str, platform: str):
        day = datetime.now()
        folder = Path(self.cfg["saveDir"]) / safe(platform) / safe(r.name)
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / f"{safe(r.name)}_{day:%Y-%m-%d_%H-%M-%S}.ts"
        cmd = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
               "-rw_timeout", "15000000", "-user_agent", REC_UA]
        if HEADERS.get(platform):
            cmd += ["-headers", HEADERS[platform]]
        cmd += ["-analyzeduration", "20000000", "-probesize", "10000000", "-fflags", "+discardcorrupt",
                "-i", url, "-c", "copy", "-sn", "-dn", "-map", "0:v?", "-map", "0:a?"]
        lim = self.account.limits
        if lim["hours"]:
            left = lim["hours"] * 3600 - r.session_secs
            if left <= 5:
                r.capped = True
                r.status = "直播中（本场已达录制上限）"
                return
            cmd += ["-t", str(int(left))]
        cmd += ["-f", "mpegts", str(f)]
        try:
            r.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, creationflags=NOWIN)
        except FileNotFoundError:
            r.status, r.error = "出错", "找不到 ffmpeg"
            return
        r.file, r.rec_start, r.status = f, time.time(), "录制中"
        self.log(f"[{r.name}] 开始录制 → {f.name}")

    def _reap(self):
        """检查录制进程：结束的收尾，超出分段时长的切段。"""
        seg = self.cfg.get("segmentMin") or 0
        with self.lock:
            for r in self.rooms:
                if not r.proc:
                    continue
                if seg and time.time() - r.rec_start >= seg * 60:
                    self._stop(r, "分段")
                    r.last_check = 0  # 马上续录下一段
                    continue
                if r.proc.poll() is not None:
                    err = (r.proc.stderr.read() or b"").decode("utf-8", "ignore").strip().splitlines()
                    self._finish(r)
                    lim = self.account.limits
                    if lim["hours"] and r.session_secs >= lim["hours"] * 3600 - 5:
                        r.capped = True
                        r.status = "直播中（本场已达录制上限）"
                        self.log(f"[{r.name}] 免费版单场录制已满 {lim['hours']} 小时，开通会员可不限时长")
                    else:
                        r.status = "等待检测"
                        if err:
                            self.log(f"[{r.name}] 录制中断：{err[-1][:100]}")
                    r.last_check = 0

    def _stop(self, r: Room, why: str):
        p = r.proc
        if not p:
            return
        try:
            p.stdin.write(b"q")
            p.stdin.flush()
            p.wait(timeout=8)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        self._finish(r)
        self.log(f"[{r.name}] 停止录制（{why}）")

    def _finish(self, r: Room):
        f, secs = r.file, time.time() - r.rec_start
        r.proc, r.file = None, None
        r.session_secs += secs
        if not f or not f.exists() or f.stat().st_size < 50 * 1024:
            if f and f.exists():
                try:
                    f.unlink()
                except Exception:
                    pass
            return
        item = {"name": r.name, "platform": r.platform, "path": str(f), "secs": int(secs),
                "size": f.stat().st_size, "t": int(time.time())}
        self.files.append(item)
        self.persist()
        self.notify("录制完成", f"{r.name} 录了 {int(secs // 60)} 分钟")
        if self.cfg.get("toMp4"):
            threading.Thread(target=self._to_mp4, args=(item,), daemon=True).start()

    def _to_mp4(self, item):
        src = Path(item["path"])
        dst = src.with_suffix(".mp4")
        p = subprocess.run([ffmpeg_path(), "-y", "-loglevel", "error", "-i", str(src), "-c", "copy",
                            "-map", "0", "-movflags", "+faststart", str(dst)],
                           capture_output=True, creationflags=NOWIN)
        if p.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
            try:
                src.unlink()
            except Exception:
                pass
            with self.lock:
                item["path"], item["size"] = str(dst), dst.stat().st_size
            self.persist()
            self.log(f"已转为 MP4：{dst.name}")
        else:
            self.log(f"转 MP4 失败，保留 TS 文件：{src.name}")

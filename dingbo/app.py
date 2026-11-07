"""盯播 · 桌面窗口（pywebview + 本地 HTML 界面）。"""
import os, subprocess, sys, threading, webbrowser
from pathlib import Path

import webview

from . import __version__
from .account import SITE
from .core import APPDIR, Manager


def res(*p) -> str:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base.joinpath(*p))


class Api:
    def __init__(self, m: Manager):
        self.m = m
        self.window = None

    # 账号
    def login(self, email, password):
        r = self.m.account.login(email, password)
        self.m.persist()
        self.m.kick()
        return r

    def logout(self):
        self.m.account.logout()
        self.m.shutdown()
        self.m.persist()
        return {"ok": True}

    def refresh_user(self):
        self.m.account.refresh()
        self.m.persist()
        return self.m.state()["user"]

    # 直播间
    def state(self):
        return self.m.state()

    def add(self, text, quality="OD"):
        if self.m.account.plan == "guest":
            return {"ok": False, "error": "请先登录网站账号"}
        return self.m.add_rooms(text, quality)

    def update(self, rid, patch):
        return self.m.update_room(rid, patch)

    def remove(self, rid):
        return self.m.remove_room(rid)

    def stop(self, rid):
        return self.m.stop_room(rid)

    def check_now(self):
        return self.m.check_now()

    def settings(self, s):
        return self.m.set_settings(s)

    def version(self):
        return {"version": __version__, "latest": self.m.account.latest_version()}

    # 文件
    def pick_dir(self):
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG, directory=self.m.cfg["saveDir"])
        if r:
            self.m.set_settings({"saveDir": r[0]})
            return r[0]
        return ""

    def open_path(self, path):
        p = Path(path)
        if not p.exists():
            p = p.parent
        p.mkdir(parents=True, exist_ok=True) if not p.exists() else None
        if sys.platform == "win32":
            os.startfile(str(p))
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True}

    def reveal(self, path):
        if sys.platform == "win32" and Path(path).exists():
            subprocess.Popen(["explorer", "/select,", str(Path(path))])
            return {"ok": True}
        return self.open_path(str(Path(path).parent))

    def open_site(self, path="/"):
        webbrowser.open(SITE + path)
        return {"ok": True}


def main():
    m = Manager()
    api = Api(m)

    def notify(title, msg):
        try:
            if api.window:
                api.window.evaluate_js(f"window.toast && toast({title!r} + '：' + {msg!r})")
        except Exception:
            pass

    m.notify = notify
    win = webview.create_window(f"盯播 {__version__} · 直播开播检测与自动录制", res("ui", "index.html"),
                                js_api=api, width=1180, height=760, min_size=(900, 600),
                                background_color="#f5f3fb")
    api.window = win

    def on_closing():
        busy = any(r.proc for r in m.rooms)
        if busy and not win.create_confirmation_dialog("退出盯播", "还有直播间正在录制，退出会停止录制（已录内容会保存）。确定退出吗？"):
            return False
        m.shutdown()
        return True

    win.events.closing += on_closing
    webview.start(debug=os.environ.get("DINGBO_DEBUG") == "1", storage_path=str(APPDIR / "webview"))


if __name__ == "__main__":
    main()

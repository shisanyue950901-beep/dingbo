# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
datas, binaries, hidden = [], [], []
for pkg in ("streamget", "webview"):
    d, b, h = collect_all(pkg); datas += d; binaries += b; hidden += h
datas += [("ui", "ui")]
binaries += [("ffmpeg/ffmpeg.exe", "ffmpeg")]
a = Analysis(["run.py"], datas=datas, binaries=binaries, hiddenimports=hidden, excludes=["tkinter", "matplotlib", "numpy"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="盯播", icon="dingbo.ico", console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Dingbo", upx=False)

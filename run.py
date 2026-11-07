import sys


def selftest(out: str) -> int:
    """CI 用：检查打包后的依赖、ffmpeg 和一个平台接口，结果写入文件。"""
    import asyncio, subprocess, traceback
    lines, code = [], 0
    try:
        from dingbo import __version__
        from dingbo.core import ffmpeg_path
        import webview, streamget
        from webview.platforms import winforms  # noqa: F401  Windows 下的 WebView2 后端
        lines.append(f"version {__version__}")
        ff = ffmpeg_path()
        v = subprocess.run([ff, "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        lines.append(f"ffmpeg {ff} | {v}")
        s = streamget.BilibiliLiveStream()
        d = asyncio.run(s.fetch_web_stream_data("https://live.bilibili.com/7734200"))
        lines.append(f"bilibili anchor={d.get('anchor_name')}")
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    return code


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest(sys.argv[sys.argv.index("--selftest") + 1]))
    from dingbo.app import main
    main()

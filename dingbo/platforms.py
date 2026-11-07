"""直播平台识别：链接 → streamget 类。"""
import re

# (正则, 平台名, streamget 类名, 优先方法)
TABLE = [
    (r"v\.douyin\.com|douyin\.com/user", "抖音", "DouyinLiveStream", "app"),
    (r"live\.douyin\.com|douyin\.com", "抖音", "DouyinLiveStream", "web"),
    (r"live\.bilibili\.com|b23\.tv", "B站", "BilibiliLiveStream", "web"),
    (r"huya\.com", "虎牙", "HuyaLiveStream", "web"),
    (r"douyu\.com", "斗鱼", "DouyuLiveStream", "web"),
    (r"kuaishou\.com", "快手", "KwaiLiveStream", "web"),
    (r"xhslink\.com|xiaohongshu\.com", "小红书", "RedNoteLiveStream", "web"),
    (r"yy\.com", "YY", "YYLiveStream", "web"),
    (r"weibo\.com", "微博", "WeiboLiveStream", "web"),
    (r"cc\.163\.com", "网易CC", "NeteaseLiveStream", "web"),
    (r"huajiao\.com", "花椒", "HuajiaoLiveStream", "web"),
    (r"acfun\.cn", "AcFun", "AcfunLiveStream", "web"),
    (r"inke\.cn", "映客", "InkeLiveStream", "web"),
    (r"6\.cn", "六间房", "SixRoomLiveStream", "web"),
    (r"kugou\.com", "酷狗", "KugouLiveStream", "web"),
    (r"live\.baidu\.com", "百度", "BaiduLiveStream", "web"),
    (r"zhihu\.com", "知乎", "ZhihuLiveStream", "web"),
    (r"taobao\.com|m\.tb\.cn", "淘宝", "TaobaoLiveStream", "web"),
    (r"3\.cn|jd\.com", "京东", "JDLiveStream", "web"),
    (r"miguvideo\.com", "咪咕", "MiguLiveStream", "web"),
    (r"tiktok\.com", "TikTok", "TikTokLiveStream", "web"),
    (r"youtube\.com|youtu\.be", "YouTube", "YoutubeLiveStream", "web"),
    (r"twitch\.tv", "Twitch", "TwitchLiveStream", "web"),
    (r"sooplive\.co\.kr|soop", "SOOP", "SoopLiveStream", "web"),
    (r"bigo\.tv", "Bigo", "BigoLiveStream", "web"),
]

# 录制时需要的额外请求头
HEADERS = {
    "B站": "referer: https://live.bilibili.com\r\n",
    "斗鱼": "referer: https://www.douyu.com\r\n",
    "虎牙": "referer: https://www.huya.com\r\n",
}

URL_RE = re.compile(r"https?://[^\s，,。]+")


def extract_urls(text: str) -> list[str]:
    return [u.rstrip(")）】") for u in URL_RE.findall(text or "")]


def detect(url: str):
    for pat, name, cls, how in TABLE:
        if re.search(pat, url, re.I):
            return name, cls, how
    return None

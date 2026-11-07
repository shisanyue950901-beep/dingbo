# 盯播 · 直播间开播检测与自动录制

盯着你关注的直播间，**开播即录、下播即停**，录像保存在你自己的电脑里。
「[视频全自动下载](https://qushuiyin.asia)」出品，使用网站账号登录，会员权益自动同步。

## 下载
到 [Releases](https://github.com/shisanyue950901-beep/dingbo/releases/latest) 下载 `Dingbo-版本号-win64.zip`，解压后双击 `盯播.exe`。

- 系统：Windows 10 / 11（64 位，需自带的 Edge WebView2，一般已安装）
- 没有代码签名，Windows 可能提示「已保护你的电脑」：点「更多信息 → 仍要运行」。

## 功能
- 粘贴直播间链接（可一次多条），支持抖音、B站、虎牙、斗鱼、快手、小红书、YY、微博、网易CC、花椒、AcFun、TikTok、YouTube、Twitch 等
- 循环检测开播状态（默认 60 秒一轮），开播自动录制、下播自动停止、断流自动续录
- 选择画质（原画 / 超清 / 高清 / 标清 / 流畅）
- 边录边存 TS，结束自动转 MP4；可按 30 / 60 / 120 分钟分段
- 录制文件列表、一键打开所在文件夹、运行日志
- 视频下载：粘贴抖音、小红书、B站分享链接去水印下载到本地（解析次数与网站共用），可一键跳到 qushuiyin.asia 做 AI 拆解、提取文案

## 套餐
| | 免费版 | Plus | Pro |
|---|---|---|---|
| 同时检测直播间 | 3 个 | 20 个 | 100 个 |
| 同时录制 | 1 个 | 3 个 | 10 个 |
| 单场录制时长 | 2 小时 | 不限 | 不限 |

会员在网站 [qushuiyin.asia/vip](https://qushuiyin.asia/vip) 开通。

## 从源码运行
```bash
pip install -r requirements.txt
python run.py          # 需要系统里有 ffmpeg
```

## 声明
仅供录制公开直播、个人学习留存使用。请遵守各平台用户协议及著作权相关法律法规，不得用于侵权传播。
第三方组件见 [NOTICE.md](NOTICE.md)。

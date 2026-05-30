# astrbot_plugin_bili_note

AstrBot 插件：自动识别 QQ 聊天中分享的 Bilibili 视频小程序/链接/BV 号，提取视频内容并用 AI 生成结构化视频总结。

## 灵感来源

本项目整合了以下两个优秀插件的功能：

- **视频总结流水线** — 来自 [storyAura/astrbot_plugin_biliVideo](https://github.com/storyAura/astrbot_plugin_biliVideo)：yt-dlp 音频/字幕下载、必剪 ASR 转写、LLM 结构化总结
- **QQ 小程序自动检测 + Cookie 登录** — 来自 [Soulter/astrbot_plugin_bilibili](https://github.com/Soulter/astrbot_plugin_bilibili)：解析 QQ 聊天中的 B 站小程序 JSON 卡片，提取视频直链

## 功能

- **零命令自动识别**：QQ 群内分享 B 站视频小程序卡片、`b23.tv` 短链、`BV` 号或完整链接，机器人自动返回视频信息并生成 AI 总结
- **AI 视频总结**：基于字幕/音频转写 + LLM，生成带章节结构的 Markdown 总结（支持 concise/detailed/professional 三种风格）
- **扫码登录**：`/bili_login` 在私聊中扫码登录 B 站，Cookie 持久化保存
- **手动总结**：`/总结 <链接或BV号>` 手动触发

## 依赖

- `aiohttp` — 异步 HTTP 请求
- `yt-dlp` — 视频音频/字幕下载
- `requests` — 必剪 ASR 接口
- `segno` — 登录二维码生成
- `ffmpeg`（系统级，可选）— 仅在视频无字幕时用于音频转码

## 命令

| 命令 | 说明 |
|------|------|
| `/总结 <链接/BV号>` | 手动生成视频总结 |
| `/bili_login` | 扫码登录 B 站（仅私聊） |
| `/bili_logout` | 登出 B 站 |
| `/bili_status` | 查看插件状态 |

## 配置说明

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enable_miniapp_detect` | true | 自动识别 B 站链接/小程序 |
| `detect_auto_summary` | true | 识别到视频后自动生成总结 |
| `note_style` | professional | 总结风格：concise / detailed / professional |
| `prefer_subtitle` | true | 优先使用平台字幕 |
| `sessdata` | (空) | 手动填入 B 站 Cookie，也可扫码登录 |

## 致谢

本插件整合了两个优秀项目的功能：

- [storyAura/astrbot_plugin_biliVideo](https://github.com/storyAura/astrbot_plugin_biliVideo) — 视频下载、ASR 转写、LLM 总结流水线
- [Soulter/astrbot_plugin_bilibili](https://github.com/Soulter/astrbot_plugin_bilibili) — QQ 小程序自动检测、Cookie 登录方案

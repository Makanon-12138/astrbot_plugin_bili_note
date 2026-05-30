"""
astrbot_plugin_bili_note
整合 B站视频自动识别 + AI 总结功能

灵感来源:
- Mini-app 自动检测: Soulter/astrbot_plugin_bilibili (https://github.com/Soulter/astrbot_plugin_bilibili)
- 视频总结生成: storyAura/astrbot_plugin_biliVideo (https://github.com/storyAura/astrbot_plugin_biliVideo)
- Cookie 登录: 基于 B站 HTTP API 直接实现

自动识别 QQ 聊天中的 Bilibili 小程序/链接/BV号，
提取视频内容并生成 AI 结构化的视频总结。
"""
import asyncio
import json
import os
import re
import tempfile
from typing import Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent, MessageChain, MessageEventResult
from astrbot.api.event.filter import (
    EventMessageType,
    PermissionType,
    command,
    event_message_type,
    permission_type,
    regex,
)
from astrbot.api.star import Context, Star, StarTools

from .core.constant import BV_REGEX, PLUGIN_NAME
from .core.data_manager import DataManager
from .services.bilibili_api import get_video_info, resolve_short_url
from .services.bilibili_login import BilibiliLogin
from .services.note_service import NoteService


@register(PLUGIN_NAME, "Makanon-12138", "", "", "")
class BiliNotePlugin(Star):
    """B站视频自动识别+AI总结插件"""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.cfg = config

        # --- Mini-app 检测设置 (运行时从 cfg 读取，支持热更新) ---
        self.data_dir = str(StarTools.get_data_dir(PLUGIN_NAME))
        os.makedirs(self.data_dir, exist_ok=True)

        # 访问控制（初始化时确定，运行时不变）
        self.access_mode = self.cfg.get("access_mode", "blacklist")
        self.group_list = self._parse_list(str(self.cfg.get("group_list", "")))

        # --- 代理 ---
        self.proxy = (self.cfg.get("proxy", "") or "").strip()

        # --- 数据管理 ---
        self.data_manager = DataManager()

        # --- B站登录 ---
        self.bili_login = BilibiliLogin(self.data_dir)
        if not self.bili_login.is_logged_in():
            # 尝试从持久化的凭据恢复（扫码登录保存的）
            saved_credential = self.data_manager.get_credential()
            if saved_credential:
                cookies = BilibiliLogin.from_dict(saved_credential)
                if cookies.get("SESSDATA"):
                    self.bili_login._save(cookies)
                    logger.info("已从数据文件恢复 B站凭据")
            # 尝试从配置中的 SESSDATA 恢复
            if not self.bili_login.is_logged_in():
                sessdata = self.cfg.get("sessdata", "") or ""
                if sessdata:
                    cookies = BilibiliLogin.from_dict({"sessdata": sessdata})
                    if cookies.get("SESSDATA"):
                        self.bili_login._save(cookies)
                        logger.info("已从配置 SESSDATA 恢复 B站凭据")

        # --- 初始化总结服务 ---
        bili_cookies = self.bili_login.get_cookie_dict() if self.bili_login.is_logged_in() else {}
        self.note_service = NoteService(
            data_dir=self.data_dir,
            cookies=bili_cookies if bili_cookies else None,
        )

        logger.info(
            f"BilibiliSummary 插件已加载 | 自动识别: {'开' if self.cfg.get('enable_miniapp_detect', True) else '关'} "
            f"| 自动总结: {'开' if self.cfg.get('detect_auto_summary', True) else '关'} "
            f"| B站: {'已登录' if self.bili_login.is_logged_in() else '未登录'}"
        )

    # ==================== 工具方法 ====================

    @staticmethod
    def _parse_list(text: str) -> set:
        if not text or not text.strip():
            return set()
        return {item.strip() for item in text.split(',') if item.strip()}

    def _check_access(self, event: AstrMessageEvent) -> bool:
        try:
            origin = getattr(event, 'unified_msg_origin', '') or ''
            if self.access_mode == 'all' or not self.group_list:
                return True
            if self.access_mode == 'whitelist':
                for gid in self.group_list:
                    if f':{gid}' in origin or origin.endswith(gid):
                        return True
                return False
            elif self.access_mode == 'blacklist':
                for gid in self.group_list:
                    if f':{gid}' in origin or origin.endswith(gid):
                        return False
                return True
        except Exception as e:
            logger.warning(f"访问控制检查异常: {e}")
        return True

    async def _ask_llm(self, prompt: str) -> Optional[str]:
        """调用 LLM 生成回复"""
        llm_provider = self.cfg.get("llm_provider", "astrbot")
        if llm_provider == "astrbot":
            try:
                provider = self.context.get_using_provider()
                if provider:
                    resp = await provider.text_chat(prompt, session_id=None)
                    if hasattr(resp, 'completion_text'):
                        return resp.completion_text
                    return str(resp)
                else:
                    logger.error("AstrBot LLM provider 未就绪")
                    return None
            except Exception as e:
                logger.error(f"AstrBot LLM 调用失败: {e}")
                return None
        elif llm_provider == "openai_compatible":
            import aiohttp
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cfg.get('llm_api_key', '')}",
            }
            payload = {
                "model": self.cfg.get("llm_model", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
            }
            try:
                async with aiohttp.ClientSession() as session:
                    api_base = str(self.cfg.get("llm_api_base", "")).rstrip("/")
                    async with session.post(
                        f"{api_base}/chat/completions",
                        json=payload, headers=headers,
                        timeout=aiohttp.ClientTimeout(total=120),
                    ) as resp:
                        if resp.status != 200:
                            logger.error(f"OpenAI API 返回 {resp.status}")
                            return None
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]
            except Exception as e:
                logger.error(f"OpenAI API 调用失败: {e}")
                return None
        return None

    def _get_bili_cookies(self) -> Optional[dict]:
        if self.bili_login.is_logged_in():
            return self.bili_login.get_cookie_dict()
        return None

    # ==================== 小程序 / JSON 卡片解析 ====================

    @staticmethod
    def _try_parse_json_for_url(text: str) -> Optional[str]:
        """尝试从 JSON 文本中提取 B站视频链接"""
        try:
            if isinstance(text, dict):
                data = text
            else:
                data = json.loads(text)

            # 路径 A: meta.detail_1 (小程序卡片)
            meta = data.get("meta", {})
            detail_1 = meta.get("detail_1", {})
            if detail_1.get("title") == "哔哩哔哩":
                qqdocurl = detail_1.get("qqdocurl", "")
                if qqdocurl:
                    return qqdocurl
                desc = detail_1.get("desc", "")
                if desc:
                    return desc

            # 路径 B: meta.news (新闻卡片)
            news = meta.get("news", {})
            if news.get("tag") == "哔哩哔哩":
                jumpurl = news.get("jumpUrl", "")
                if jumpurl:
                    return jumpurl

            # 路径 C: app (小程序 JSON)
            app = data.get("app", "")
            if app and isinstance(app, str):
                if "bilibili" in app.lower():
                    qqdoc_match = re.search(r'"qqdocurl"\s*:\s*"(https?://[^"]+)"', app)
                    if qqdoc_match:
                        return qqdoc_match.group(1)

            # 路径 D: prompt (纯文本中的链接)
            prompt = data.get("prompt", "")
            if prompt and "bilibili" in prompt.lower():
                url_match = re.search(r'(https?://[^\s]+bilibili[^\s]*)', prompt)
                if url_match:
                    return url_match.group(0)

            # 路径 E: detail_1.desc 可能本身就是链接
            desc = detail_1.get("desc", "")
            if desc and "bilibili" in desc.lower():
                url_match = re.search(r'https?://b23\.tv/\S+|https?://(?:www\.)?bilibili\.com/video/BV\w+', desc)
                if url_match:
                    return url_match.group(0).rstrip('"}\']')

            return None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def _extract_bili_url_from_raw(raw) -> Optional[str]:
        """从 raw 数据中提取 B站 URL"""
        if isinstance(raw, (dict, list)):
            return BilibiliSummaryPlugin._try_parse_json_for_url(raw)
        elif isinstance(raw, str):
            if raw.strip().startswith("{") or raw.strip().startswith("["):
                return BilibiliSummaryPlugin._try_parse_json_for_url(raw.strip())
            url_match = re.search(r'https?://b23\.tv/\S+|https?://(?:www\.)?bilibili\.com/video/BV\w+', raw)
            if url_match:
                return url_match.group(0).rstrip('"}\']')
            qqdoc_match = re.search(r'"qqdocurl"\s*:\s*"(https?://[^"]+)"', raw)
            if qqdoc_match:
                return qqdoc_match.group(1)
        return None

    # ==================== 自动识别 B站链接 ====================

    @event_message_type(EventMessageType.ALL)
    async def on_miniapp_and_bv(self, event: AstrMessageEvent):
        """
        自动识别消息中的 B站内容:
        1. QQ 小程序 JSON 卡片 (Bilibili 分享)
        2. 消息文本中的 B站链接 / BV号
        """
        msg_str = event.message_str or ""
        raw_msg_str = ""
        if hasattr(event, 'message_obj') and event.message_obj:
            raw_msg_str = str(getattr(event.message_obj, 'raw_message', ''))

        # 跳过引用消息中的链接（避免重复触发）
        if "[CQ:reply" in raw_msg_str or "[CQ:reply" in msg_str:
            return

        # 跳过命令消息
        if msg_str.strip().startswith("/"):
            return

        # 访问控制
        if not self._check_access(event):
            return

        bili_url = ""
        bvid = None

        # === 1. 从消息组件解析 JSON 小程序 ===
        if self.cfg.get("enable_miniapp_detect", True):
            try:
                if hasattr(event, 'message_obj') and event.message_obj:
                    for msg_element in event.message_obj.message:
                        comp_type = getattr(msg_element, 'type', '') or ''
                        if comp_type == 'Json':
                            json_data = msg_element.data
                            extracted = self._try_parse_json_for_url(json_data)
                            if extracted:
                                bili_url = extracted
                                logger.info(f"[MiniApp] 从小程序卡片提取到 URL: {bili_url}")
                                break

                    # 兜底：遍历组件的 raw/data 属性
                    if not bili_url:
                        for i, comp in enumerate(event.message_obj.message):
                            comp_raw = getattr(comp, 'raw', None) or getattr(comp, 'data', None)
                            if comp_raw:
                                extracted = self._extract_bili_url_from_raw(comp_raw)
                                if extracted:
                                    bili_url = extracted
                                    break

                    # 继续兜底：将组件转为字符串后解析
                    if not bili_url:
                        for comp in event.message_obj.message:
                            comp_str = str(comp)
                            if 'bilibili' in comp_str.lower() or 'b23.tv' in comp_str.lower():
                                extracted = self._try_parse_json_for_url(comp_str)
                                if extracted:
                                    bili_url = extracted
                                    break
                                qqdoc_match = re.search(r'"qqdocurl"\s*:\s*"(https?://[^"]+)"', comp_str)
                                if qqdoc_match:
                                    bili_url = qqdoc_match.group(1)
                                    break
                                url_match = re.search(r'https?://(?:www\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10})', comp_str)
                                if url_match:
                                    bvid = url_match.group(1)
                                    break
            except Exception as e:
                logger.error(f"[MiniApp] 解析异常: {e}", exc_info=True)

        # === 2. 从 raw_message 提取 ===
        if not bili_url and not bvid and raw_msg_str.strip().startswith("{"):
            bili_url = self._try_parse_json_for_url(raw_msg_str.strip())

        # === 3. 从提取到的 URL 获取 BV 号 ===
        if bili_url and not bvid:
            logger.info(f"[AutoDetect] 提取到 URL: {bili_url}")
            bv_match = re.search(r'BV([0-9A-Za-z]{10})', bili_url)
            if bv_match:
                bvid = f"BV{bv_match.group(1)}"
            elif 'b23.tv' in bili_url:
                resolved = await resolve_short_url(bili_url)
                if resolved:
                    bv_match = re.search(r'BV([0-9A-Za-z]{10})', resolved)
                    if bv_match:
                        bvid = f"BV{bv_match.group(1)}"

        # === 4. 从消息文本提取 BV 号 ===
        if not bvid:
            bv_match = re.search(r'BV([0-9A-Za-z]{10})', msg_str, re.IGNORECASE)
            if bv_match:
                bvid = f"BV{bv_match.group(1)}"

            # 从文本中的 b23 短链接提取
            if not bvid:
                short_match = re.search(r'https?://b23\.tv/(\w+)', msg_str)
                if short_match:
                    resolved = await resolve_short_url(short_match.group(0))
                    if resolved:
                        bv_match = re.search(r'BV([0-9A-Za-z]{10})', resolved)
                        if bv_match:
                            bvid = f"BV{bv_match.group(1)}"

        if not bvid:
            return

        logger.info(f"[AutoDetect] 识别到视频 BV: {bvid}")

        # === 获取视频信息 ===
        video_info = await get_video_info(bvid, cookies=self._get_bili_cookies())

        # === 发送视频信息卡片（可配置开关）===
        if self.cfg.get("detect_show_video_info", True):
            if video_info:
                info_lines = []
                if self.cfg.get("detect_show_uploader", True):
                    info_lines.append(f"UP主: {video_info.get('owner_name', '未知')}")
                if self.cfg.get("detect_show_desc", True):
                    desc = video_info.get('desc', '')
                    if desc:
                        desc = desc[:100] + "..." if len(desc) > 100 else desc
                        info_lines.append(f"简介: {desc}")
                if self.cfg.get("detect_show_stats", True):
                    info_lines.append(
                        f"播放: {video_info.get('view', 0)} | "
                        f"弹幕: {video_info.get('danmaku', 0)} | "
                        f"点赞: {video_info.get('like', 0)}"
                    )
                info_lines.append(f"链接: https://www.bilibili.com/video/{bvid}")

                chain = MessageChain()
                chain.message("📺 " + video_info.get('title', 'B站视频'))
                if info_lines:
                    chain.message("\n" + "\n".join(info_lines))
                if self.cfg.get("detect_show_cover", True):
                    pic_url = video_info.get('pic', '')
                    if pic_url:
                        chain.url_image(pic_url)
                try:
                    await event.send(chain)
                except Exception as e:
                    logger.warning(f"发送视频信息失败: {e}")
            else:
                try:
                    await event.send_result("获取视频信息失败，请稍后重试")
                except Exception:
                    pass
                return

        # === 自动生成总结（如果开启）===
        if self.cfg.get("detect_auto_summary", True):
            await self._do_summarize(event, f"https://www.bilibili.com/video/{bvid}")

    # ==================== BV 链接正则匹配 ====================

    @regex(BV_REGEX)
    async def on_bv_regex(self, event: AstrMessageEvent):
        """当消息中出现 BV 号时获取视频信息（备用检测）"""
        # on_miniapp_and_bv 已经处理了，这里作为备用
        pass

    # ==================== /总结 命令 ====================

    @command("总结", alias={"bili_summary", "视频总结", "BiliVideo"})
    async def cmd_summarize(self, event: AstrMessageEvent, url: str | None = None):
        """
        手动触发视频总结

        用法:
        /总结 https://www.bilibili.com/video/BVxxx
        /总结 BVxxx
        /总结 https://b23.tv/xxx
        """
        if not self._check_access(event):
            return

        msg_str = event.message_str or ""

        # 提取命令后的参数
        parts = msg_str.strip().split(maxsplit=1)
        if len(parts) > 1:
            url = parts[1].strip()
        elif url:
            pass  # 框架已解析
        else:
            yield event.plain_result(
                "用法: /总结 <B站视频链接或BV号>\n"
                "例如: /总结 https://www.bilibili.com/video/BV1xx\n"
                "或直接分享B站视频小程序/链接，机器人会自动识别"
            )
            return

        await self._do_summarize(event, url)

    async def _do_summarize(self, event: AstrMessageEvent, url: str):
        """执行视频总结"""
        # 确保 URL 完整
        if not url.startswith("http"):
            if re.match(r'^BV[0-9A-Za-z]{10}$', url):
                url = f"https://www.bilibili.com/video/{url}"
            else:
                bv_match = re.search(r'BV[0-9A-Za-z]{10}', url)
                if bv_match:
                    url = f"https://www.bilibili.com/video/{bv_match.group(0)}"
                else:
                    try:
                        await event.send_result("请提供有效的B站视频链接或BV号")
                    except Exception:
                        pass
                    return

        try:
            await event.send_result("正在生成视频总结，请稍候...")
        except Exception:
            pass

        try:
            note = await asyncio.wait_for(
                self.note_service.generate_note(
                    video_url=url,
                    llm_ask_func=self._ask_llm,
                    style=self.cfg.get("note_style", "professional"),
                    enable_summary=self.cfg.get("enable_summary_block", True),
                    quality=self.cfg.get("download_quality", "fast"),
                    max_length=self.cfg.get("max_note_length", 3000),
                    prefer_subtitle=self.cfg.get("prefer_subtitle", True),
                ),
                timeout=self.cfg.get("processing_timeout", 300),
            )

            if not note:
                try:
                    await event.send_result("总结生成失败，请稍后重试")
                except Exception:
                    pass
                return

            if note.startswith("无法获取"):
                try:
                    await event.send_result(f"❌ {note}")
                except Exception:
                    pass
                return

            note = note.replace("*", "").replace("#", "").replace("`", "")

            # 发送总结
            if len(note) > 2000:
                chunks = []
                remaining = note
                while remaining:
                    if len(remaining) <= 2000:
                        chunks.append(remaining)
                        break
                    cut = remaining.rfind('\n', 0, 2000)
                    if cut < 500:
                        cut = 2000
                    chunks.append(remaining[:cut])
                    remaining = remaining[cut:].lstrip('\n')

                for i, chunk in enumerate(chunks):
                    label = f"📝 视频总结 ({i + 1}/{len(chunks)})\n\n" if i > 0 else "📝 视频总结\n\n"
                    try:
                        await event.send_result(label + chunk)
                    except Exception:
                        pass
            else:
                try:
                    await event.send_result(f"📝 视频总结\n\n{note}")
                except Exception:
                    pass

        except asyncio.TimeoutError:
            logger.error(f"总结超时 ({self.processing_timeout}s): {url}")
            try:
                await event.send_result(f"总结生成超时（{self.processing_timeout}秒），请尝试较短的视频或在配置中增加超时时间")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"总结失败: {e}", exc_info=True)
            try:
                await event.send_result(f"总结生成失败: {str(e)[:200]}")
            except Exception:
                pass

    # ==================== B站登录命令 ====================

    @command("bili_login", alias={"B站登录", "bilibili_login"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_bili_login(self, event: AstrMessageEvent):
        """扫码登录 Bilibili"""
        if event.get_group_id():
            yield event.plain_result("仅支持在私聊中使用扫码登录")
            return

        qr_data = await self.bili_login.generate_qrcode()
        if not qr_data:
            yield event.plain_result("获取登录二维码失败，请稍后重试")
            return

        qrcode_key = qr_data["qrcode_key"]
        qr_url = qr_data["url"]

        # 生成二维码图片
        qr_path = os.path.join(tempfile.gettempdir(), "bilibili_login_qrcode.png")
        self.bili_login.save_qrcode_image(qr_url, qr_path)

        yield MessageChain().message("请使用 Bilibili App 扫描下方二维码登录：").file_image(qr_path)

        elapsed = 0
        timeout = 180
        interval = 2
        last_status = None

        while elapsed < timeout:
            result = await self.bili_login.poll_login(qrcode_key)
            status = result["status"]

            if status != last_status:
                last_status = status
                if status == "success":
                    cred_dict = self.bili_login.get_credential_dict()
                    if cred_dict:
                        await self.data_manager.set_credential(cred_dict)
                        self.note_service = NoteService(
                            data_dir=self.data_dir,
                            cookies=self.bili_login.get_cookie_dict(),
                        )
                    yield event.plain_result("B站登录成功！")
                    return
                elif status == "scanned":
                    yield event.plain_result("已扫描，请在手机上确认登录...")
                elif status == "expired":
                    yield event.plain_result("二维码已过期，请重新执行 /bili_login")
                    return
                elif status == "error":
                    yield event.plain_result("登录出错，请重试")
                    return

            await asyncio.sleep(interval)
            elapsed += interval

        yield event.plain_result("登录超时，请重新执行 /bili_login")

    @command("bili_logout", alias={"B站登出", "bilibili_logout"})
    @permission_type(PermissionType.ADMIN)
    async def cmd_bili_logout(self, event: AstrMessageEvent):
        """登出 Bilibili"""
        self.bili_login.logout()
        await self.data_manager.clear_credential()
        self.note_service = NoteService(data_dir=self.data_dir, cookies=None)
        return MessageEventResult().message("已登出 Bilibili，凭据已清除。")

    @command("bili_status", alias={"B站状态", "bilibili_status"})
    async def cmd_bili_status(self, event: AstrMessageEvent):
        """查看B站登录状态和插件配置"""
        lines = [
            "📊 Bilibili Summary 状态",
            f"B站登录: {'已登录' if self.bili_login.is_logged_in() else '未登录'}",
            f"自动识别: {'开启' if self.cfg.get('enable_miniapp_detect', True) else '关闭'}",
            f"自动总结: {'开启' if self.cfg.get('detect_auto_summary', True) else '关闭'}",
            f"总结风格: {self.cfg.get('note_style', 'professional')}",
            f"优先字幕: {'是' if self.cfg.get('prefer_subtitle', True) else '否'}",
            f"LLM提供者: {self.cfg.get('llm_provider', 'astrbot')}",
            f"最大长度: {self.cfg.get('max_note_length', 3000)}字符",
            "",
            "命令:",
            "  /总结 <链接> - 手动总结视频",
            "  /bili_login - 扫码登录B站",
            "  /bili_logout - 登出B站",
            "  /bili_status - 查看此状态",
        ]
        return MessageEventResult().message("\n".join(lines))

    async def terminate(self):
        """插件卸载时清理"""
        logger.info("BilibiliSummary 插件已卸载")

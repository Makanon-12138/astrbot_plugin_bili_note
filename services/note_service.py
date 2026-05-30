"""
视频总结生成服务

流程: 获取字幕 → 下载音频 → ASR转写 → LLM总结 → 后处理
"""
import asyncio
import os
from typing import Optional

from astrbot.api import logger

from ..downloaders.bilibili_downloader import BilibiliDownloader
from ..transcriber.bcut import BcutTranscriber
from ..gpt.prompt_builder import build_prompt, build_review_prompt
from ..utils.note_helper import replace_content_markers
from ..utils.url_parser import extract_video_id


class NoteService:
    """总结生成服务"""

    def __init__(self, data_dir: str, cookies: Optional[dict] = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.downloader = BilibiliDownloader(
            data_dir=os.path.join(data_dir, "audio"),
            cookies=cookies,
        )
        self.transcriber = BcutTranscriber()
        self.cookies = cookies
        self._last_segments = None
        self._last_title = ""
        self._last_url = ""

    async def generate_note(
        self,
        video_url: str,
        llm_ask_func,
        style: str = "detailed",
        enable_summary: bool = True,
        quality: str = "fast",
        max_length: int = 3000,
        prefer_subtitle: bool = True,
        max_input_chars: int = 0,
    ) -> Optional[str]:
        try:
            audio_meta = None
            transcript = None

            # 1. 尝试获取平台字幕
            if prefer_subtitle:
                logger.info(f"尝试获取平台字幕: {video_url}")
                transcript = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.downloader.download_subtitles(video_url),
                )
                if transcript and transcript.segments:
                    logger.info(f"获取字幕成功，共 {len(transcript.segments)} 段")
                else:
                    logger.info("无平台字幕，将下载音频")

            # 2. 下载音频
            if not transcript or not transcript.segments:
                logger.info(f"开始下载音频: {video_url}")
                audio_meta = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: self.downloader.download(video_url, quality=quality),
                )
                logger.info(f"音频下载完成: {audio_meta.title}")

                # 3. ASR 转写
                if not transcript or not transcript.segments:
                    logger.info("使用必剪转写...")
                    transcript = await asyncio.get_running_loop().run_in_executor(
                        None,
                        lambda: self.transcriber.transcript(audio_meta.file_path),
                    )

            if not transcript or not transcript.segments:
                return "无法获取视频内容（字幕和转写均失败）"

            logger.info(f"获取到 {len(transcript.segments)} 段转写内容")

            # 4. 确定标题
            tags = ""
            title = ""
            if audio_meta:
                raw_info = audio_meta.raw_info or {}
                if isinstance(raw_info.get("tags"), list):
                    tags = ", ".join(raw_info["tags"])
                elif isinstance(raw_info.get("tags"), str):
                    tags = raw_info["tags"]
                title = audio_meta.title
            else:
                title = "视频总结"
                video_id = extract_video_id(video_url, "bilibili")
                if video_id:
                    try:
                        from ..services.bilibili_api import get_video_info
                        video_info = await get_video_info(video_id, cookies=self.cookies)
                        if video_info:
                            title = video_info.get("title", "")
                    except Exception as e:
                        logger.warning(f"获取视频标题失败: {e}")

            # 缓存供 generate_review 复用
            self._last_segments = transcript.segments
            self._last_title = title
            self._last_url = video_url

            # 5. 构建 Prompt 并调用 LLM

            prompt = build_prompt(
                title=title,
                segments=transcript.segments,
                tags=tags,
                style=style,
                enable_summary=enable_summary,
                max_input_chars=max_input_chars,
            )

            logger.info("调用 LLM 生成总结...")
            markdown = await llm_ask_func(prompt)

            if not markdown:
                return "LLM 生成总结失败"

            # 5. 后处理
            video_id = extract_video_id(video_url, "bilibili")
            if video_id:
                markdown = replace_content_markers(markdown, video_id=video_id, platform="bilibili")

            # 6. 截断
            if len(markdown) > max_length:
                truncated = markdown[:max_length]
                min_keep = int(max_length * 0.7)
                last_newline = truncated.rfind('\n\n')
                if last_newline > min_keep:
                    truncated = truncated[:last_newline]
                markdown = truncated + (
                    f"\n\n---\n\n"
                    f"[内容过长，已截断至 {max_length} 字符]\n"
                    f"以上为核心内容摘要。"
                )

            return markdown

        except Exception as e:
            logger.error(f"总结生成失败: {e}", exc_info=True)
            return self._format_error(e)
        finally:
            try:
                if 'audio_meta' in locals() and audio_meta and hasattr(audio_meta, 'file_path'):
                    self._cleanup(audio_meta.file_path)
            except Exception:
                pass

    async def generate_review(self, llm_ask_func, max_input_chars: int = 0) -> Optional[str]:
        """基于缓存的转写内容生成观后感/评论（需先调用 generate_note）"""
        if not self._last_segments:
            return "暂无视频内容可评论"
        prompt = build_review_prompt(
            title=self._last_title,
            segments=self._last_segments,
            max_input_chars=max_input_chars,
        )
        logger.info("调用 LLM 生成观后感...")
        return await llm_ask_func(prompt)

    @staticmethod
    def _format_error(exception: Exception) -> str:
        error_str = str(exception).lower()
        if any(k in error_str for k in ['resolve', 'dns', 'connection', 'timeout', 'network', 'connect']):
            return "网络连接失败，请检查网络后重试"
        if any(k in error_str for k in ['ffmpeg', 'ffprobe']):
            return "视频处理需要 ffmpeg，请安装后重试（下载: https://ffmpeg.org）"
        if any(k in error_str for k in ['download', '403', '404', 'forbidden', 'copyright']):
            return "视频音频下载失败，可能是版权限制或视频已删除"
        if any(k in error_str for k in ['transcript', 'transcribe', 'bcut', 'subtitle']):
            return "视频转写失败，请稍后重试或尝试其他视频"
        if any(k in error_str for k in ['llm', 'provider', 'api', 'token', 'rate limit', 'quota']):
            return "AI 服务暂时不可用，请稍后重试"
        return "总结生成失败，请重试或尝试较短的视频"

    @staticmethod
    def _cleanup(file_path: str):
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"已清理临时文件: {file_path}")
        except Exception as e:
            logger.warning(f"清理文件失败: {e}")

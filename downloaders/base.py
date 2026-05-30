from abc import ABC, abstractmethod
from typing import List, Optional

from ..models.audio_model import AudioDownloadResult
from ..models.transcriber_model import TranscriptResult

QUALITY_MAP = {
    "fast": "32",
    "medium": "64",
    "slow": "128",
}


class Downloader(ABC):
    def __init__(self):
        self.quality = QUALITY_MAP.get('fast')

    @abstractmethod
    def download(self, video_url: str, output_dir: Optional[str] = None,
                 quality: str = "fast") -> AudioDownloadResult:
        """下载音频"""
        pass

    def download_subtitles(self, video_url: str, output_dir: Optional[str] = None,
                           langs: Optional[List[str]] = None) -> Optional[TranscriptResult]:
        """获取平台字幕"""
        return None

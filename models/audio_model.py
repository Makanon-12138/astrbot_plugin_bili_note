from dataclasses import dataclass
from typing import Optional


@dataclass
class AudioDownloadResult:
    file_path: str
    title: str
    duration: float
    cover_url: Optional[str]
    platform: str
    video_id: str
    raw_info: dict

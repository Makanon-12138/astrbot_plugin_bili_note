from dataclasses import dataclass
from typing import List, Optional


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    language: Optional[str]
    full_text: str
    segments: List[TranscriptSegment]
    raw: Optional[dict] = None

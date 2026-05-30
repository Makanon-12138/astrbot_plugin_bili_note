import re
from typing import Optional


def detect_platform(url: str) -> Optional[str]:
    url_lower = url.lower()
    if 'bilibili.com' in url_lower or 'b23.tv' in url_lower:
        return 'bilibili'
    return None


def extract_video_id(url: str, platform: str) -> Optional[str]:
    if platform == "bilibili":
        match = re.search(r"BV([0-9A-Za-z]+)", url)
        return f"BV{match.group(1)}" if match else None
    return None


def extract_bilibili_mid(text: str) -> Optional[str]:
    text = text.strip()
    if text.isdigit():
        return text
    match = re.search(r"space\.bilibili\.com/(\d+)", text)
    if match:
        return match.group(1)
    return None

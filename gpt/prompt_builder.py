from .prompt import BASE_PROMPT, AI_SUM, REVIEW_PROMPT
from ..models.transcriber_model import TranscriptSegment
from typing import List, Optional


NOTE_STYLES = {
    'concise': (
        '**简洁模式**: 仅提取核心观点和关键结论，每个章节用简短的要点概括。'
        '省略细节和举例，只保留最重要的信息。整体控制在 5-8 个要点以内。'
        '每个要点用一句话概括，使用 `## 章节标题` 来分隔不同板块。'
    ),
    'detailed': (
        '**详细模式**: 完整记录视频内容，每个部分都包含详细讨论。'
        '保留重要的例子、数据和论证过程。使用 `## 章节标题` 来分隔不同板块，'
        '每个板块内使用列表和引用块来组织信息。需要尽可能多的记录视频内容。'
    ),
    'professional': (
        '**专业模式**: 提供深度结构化分析，包含背景概述、核心论点、数据支撑和结论建议。'
        '使用 `## 章节标题` 来分隔不同板块（如：概述、核心内容、关键数据、总结与建议）。'
        '每个板块内使用列表、引用块和加粗来突出关键信息。语言正式、逻辑清晰。'
    ),
}


def format_time(seconds: float) -> str:
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def build_segment_text(segments: List[TranscriptSegment], max_chars: int = 0) -> str:
    """将分段转写构建成文本，支持字符数限制"""
    if max_chars <= 0:
        return "\n".join(
            f"{format_time(seg.start)} - {seg.text.strip()}"
            for seg in segments
        )

    lines = []
    total = 0
    truncation_note = None
    for seg in segments:
        line = f"{format_time(seg.start)} - {seg.text.strip()}"
        if total + len(line) + 1 > max_chars and lines:
            remaining = len(segments) - len(lines)
            truncation_note = (
                f"\n\n---\n[内容过长，已截断：省略中间 {remaining} 段，"
                f"共约 {sum(len(s.text) for s in segments[len(lines):])} 字符]"
            )
            break
        lines.append(line)
        total += len(line) + 1

    text = "\n".join(lines)
    if truncation_note:
        text += truncation_note
    return text


def build_prompt(
    title: str,
    segments: List[TranscriptSegment],
    tags: str = "",
    style: Optional[str] = None,
    enable_summary: bool = True,
    max_input_chars: int = 0,
) -> str:
    segment_text = build_segment_text(segments, max_chars=max_input_chars)
    prompt = BASE_PROMPT.format(
        video_title=title,
        segment_text=segment_text,
        tags=tags,
    )
    if enable_summary:
        prompt += "\n" + AI_SUM
    if style and style in NOTE_STYLES:
        prompt += "\n" + NOTE_STYLES[style]
    return prompt


def build_review_prompt(
    title: str,
    segments: List[TranscriptSegment],
    max_input_chars: int = 0,
) -> str:
    max_chars = max_input_chars if max_input_chars > 0 else 4000
    segment_text = build_segment_text(segments, max_chars=max_chars)
    return REVIEW_PROMPT.format(video_title=title, segment_text=segment_text)

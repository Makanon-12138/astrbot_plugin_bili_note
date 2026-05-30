"""
B站 API 服务层
使用 aiohttp 直接调用 B站 HTTP API
"""
import asyncio
import uuid
from typing import Optional, Dict, List, Tuple

import aiohttp

from astrbot.api import logger

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com',
}


def _build_headers(cookies: Optional[dict] = None) -> dict:
    headers = dict(HEADERS)
    cookie_dict = dict(cookies) if cookies else {}
    if 'buvid3' not in cookie_dict:
        cookie_dict['buvid3'] = str(uuid.uuid4()) + "infoc"
    parts = [f'{k}={v}' for k, v in cookie_dict.items() if v]
    if parts:
        headers['Cookie'] = '; '.join(parts)
    return headers


async def get_video_info(bvid: str, cookies: Optional[dict] = None) -> Optional[Dict]:
    """获取视频详情"""
    url = "https://api.bilibili.com/x/web-interface/view"
    params = {"bvid": bvid}
    headers = _build_headers(cookies)

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"获取视频信息失败, HTTP {resp.status}")
                    return None
                data = await resp.json()
                if data.get("code") != 0:
                    logger.warning(f"获取视频信息失败: {data.get('message')}")
                    return None
                d = data.get("data") or {}
                owner = d.get("owner") or {}
                stat = d.get("stat") or {}
                return {
                    "bvid": d.get("bvid", bvid),
                    "title": d.get("title", ""),
                    "pic": d.get("pic", ""),
                    "desc": d.get("desc", ""),
                    "pubdate": d.get("pubdate", 0),
                    "owner_name": owner.get("name", "未知"),
                    "owner_mid": str(owner.get("mid", "")),
                    "view": stat.get("view", 0),
                    "danmaku": stat.get("danmaku", 0),
                    "like": stat.get("like", 0),
                    "coin": stat.get("coin", 0),
                    "favorite": stat.get("favorite", 0),
                }
    except Exception as e:
        logger.error(f"获取视频信息异常: {e}")
        return None


async def get_user_info(uid: int, cookies: Optional[dict] = None) -> Tuple[Optional[Dict], str]:
    """获取UP主信息"""
    url = "https://api.bilibili.com/x/space/wbi/acc/info"
    params = {"mid": uid}
    headers = _build_headers(cookies)

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return None, f"HTTP {resp.status}"
                data = await resp.json()
                if data.get("code") == -404:
                    return None, "用户不存在"
                if data.get("code") != 0:
                    return None, data.get("message", "未知错误")
                info = data.get("data") or {}
                return {
                    "mid": str(info.get("mid", uid)),
                    "name": info.get("name", "未知"),
                    "face": info.get("face", ""),
                }, ""
    except Exception as e:
        return None, str(e)


async def resolve_short_url(short_url: str) -> Optional[str]:
    """解析 b23.tv 短链接"""
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(
                short_url, allow_redirects=True,
                headers={"User-Agent": HEADERS["User-Agent"]}
            ) as resp:
                return str(resp.url)
    except Exception as e:
        logger.warning(f"解析短链接失败: {e}")
        return None


async def search_videos(
    keyword: str,
    page: int = 1,
    page_size: int = 20,
    order: str = "totalrank",
    duration: int = 0,
    cookies: Optional[dict] = None,
) -> Optional[Dict]:
    """搜索B站视频"""
    params = {
        "search_type": "video",
        "keyword": keyword,
        "page": page,
        "page_size": page_size,
        "order": order,
        "duration": duration,
    }
    url = "https://api.bilibili.com/x/web-interface/search/type"
    headers = _build_headers(cookies)

    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("code") != 0:
                    return None
                result_data = data.get("data", {})
                results = result_data.get("result", [])
                videos = []
                for item in results:
                    if item.get("type") != "video":
                        continue
                    title = item.get("title", "")
                    title = title.replace("<em class=\"keyword\">", "").replace("</em>", "")
                    videos.append({
                        "bvid": item.get("bvid", ""),
                        "aid": item.get("aid", 0),
                        "title": title,
                        "author": item.get("author", ""),
                        "mid": item.get("mid", 0),
                        "description": item.get("description", ""),
                        "pic": item.get("pic", ""),
                        "play": item.get("play", 0),
                        "danmaku": item.get("danmaku", 0),
                        "like": item.get("like", 0),
                        "duration": item.get("duration", ""),
                        "pubdate": item.get("pubdate", 0),
                        "url": f"https://www.bilibili.com/video/{item.get('bvid', '')}",
                    })
                return {
                    "results": videos,
                    "numResults": result_data.get("numResults", 0),
                }
    except Exception as e:
        logger.error(f"搜索视频异常: {e}")
        return None

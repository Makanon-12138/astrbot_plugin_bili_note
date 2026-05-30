"""
B站扫码登录服务
使用 B站 HTTP API 直接实现，无额外依赖（除 segno 生成二维码图片）
"""
import asyncio
import json
import os
from typing import Optional
from urllib.parse import unquote

import aiohttp
import segno

from astrbot.api import logger

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://www.bilibili.com',
}


class BilibiliLogin:
    """B站二维码扫码登录"""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.cookies_path = os.path.join(data_dir, "bili_cookies.json")
        self._cookies = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.cookies_path):
            try:
                with open(self.cookies_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self, cookies: dict):
        with open(self.cookies_path, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        self._cookies = cookies
        logger.info("B站 Cookie 已保存")

    def get_cookies(self) -> dict:
        return self._cookies

    def get_cookie_dict(self) -> dict:
        return dict(self._cookies)

    def is_logged_in(self) -> bool:
        return bool(self._cookies.get("SESSDATA"))

    def logout(self):
        self._cookies = {}
        try:
            if os.path.exists(self.cookies_path):
                os.remove(self.cookies_path)
        except OSError:
            pass
        logger.info("B站登录状态已清除")

    async def generate_qrcode(self) -> Optional[dict]:
        """申请二维码，返回 {"url": "...", "qrcode_key": "..."} 或 None"""
        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.get(QR_GENERATE_URL, headers=HEADERS) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if data.get("code") != 0:
                        return None
                    return data.get("data")
        except Exception as e:
            logger.error(f"申请二维码异常: {e}")
            return None

    async def poll_login(self, qrcode_key: str) -> dict:
        """
        轮询登录状态
        返回: {"status": "waiting|scanned|success|expired|error", "cookies": {...} or None}
        """
        params = {"qrcode_key": qrcode_key}
        try:
            async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
                async with session.get(QR_POLL_URL, params=params, headers=HEADERS) as resp:
                    if resp.status != 200:
                        return {"status": "error", "cookies": None}
                    data = await resp.json()
                    code = data.get("data", {}).get("code")

                    if code == 0:
                        url = data["data"].get("url", "")
                        cookies = self._parse_cookies_from_url(url)
                        for cookie in resp.cookies.values():
                            cookies[cookie.key] = cookie.value
                        if cookies.get("SESSDATA"):
                            self._save(cookies)
                            return {"status": "success", "cookies": cookies}
                        return {"status": "error", "cookies": None}
                    elif code == 86090:
                        return {"status": "scanned", "cookies": None}
                    elif code == 86038:
                        return {"status": "expired", "cookies": None}
                    elif code == 86101:
                        return {"status": "waiting", "cookies": None}
                    else:
                        return {"status": "error", "cookies": None}
        except Exception as e:
            logger.error(f"轮询登录异常: {e}")
            return {"status": "error", "cookies": None}

    @staticmethod
    def _parse_cookies_from_url(url: str) -> dict:
        cookies = {}
        if '?' not in url:
            return cookies
        query = url.split('?', 1)[1]
        for param in query.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                if key in ('SESSDATA', 'bili_jct', 'DedeUserID', 'sid'):
                    cookies[key] = unquote(value)
        return cookies

    def save_qrcode_image(self, qr_url: str, output_path: str):
        """将二维码 URL 渲染为 PNG 图片"""
        qr_img = segno.make_qr(qr_url)
        qr_img.save(output_path, scale=10, border=2)

    def get_credential_dict(self) -> Optional[dict]:
        """导出凭据字典（用于持久化到 DataManager）"""
        if not self._cookies:
            return None
        return {
            "sessdata": self._cookies.get("SESSDATA", ""),
            "bili_jct": self._cookies.get("bili_jct", ""),
            "buvid3": self._cookies.get("buvid3", ""),
            "buvid4": self._cookies.get("buvid4", ""),
            "dedeuserid": self._cookies.get("DedeUserID", ""),
        }

    @staticmethod
    def from_dict(data: dict) -> dict:
        """从持久化数据恢复 Cookie 字典"""
        cookies = {}
        mapping = {
            "sessdata": "SESSDATA",
            "bili_jct": "bili_jct",
            "buvid3": "buvid3",
            "buvid4": "buvid4",
            "dedeuserid": "DedeUserID",
        }
        for src_key, dst_key in mapping.items():
            val = data.get(src_key, "")
            if val:
                cookies[dst_key] = val
        return cookies

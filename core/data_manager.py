import asyncio
import json
import os
from typing import Any, Dict, Optional

from astrbot.api import logger
from astrbot.api.star import StarTools

from .constant import PLUGIN_NAME, DATA_DEFAULT


class DataManager:
    """凭证持久化管理"""

    def __init__(self):
        self.path = os.path.join(
            StarTools.get_data_dir(plugin_name=PLUGIN_NAME),
            f"{PLUGIN_NAME}.json",
        )
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(DATA_DEFAULT, f, ensure_ascii=False, indent=2)
            return dict(DATA_DEFAULT)
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _write_text(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    async def save(self):
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        await asyncio.to_thread(self._write_text, self.path, payload)

    def get_credential(self) -> Optional[Dict[str, Any]]:
        return self.data.get("credential")

    async def set_credential(self, credential_data: Dict[str, Any]):
        self.data["credential"] = credential_data
        await self.save()

    async def clear_credential(self):
        if "credential" in self.data:
            del self.data["credential"]
            await self.save()

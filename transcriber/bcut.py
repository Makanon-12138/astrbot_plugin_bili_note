"""
必剪 (Bcut) ASR 语音识别接口
免费在线语音转文字
"""
import json
import logging
import time
from typing import Optional, List

import requests

from ..models.transcriber_model import TranscriptSegment, TranscriptResult

logger = logging.getLogger(__name__)

API_BASE = "https://member.bilibili.com/x/bcut/rubick-interface"
API_REQ_UPLOAD = API_BASE + "/resource/create"
API_COMMIT_UPLOAD = API_BASE + "/resource/create/complete"
API_CREATE_TASK = API_BASE + "/task"
API_QUERY_RESULT = API_BASE + "/task/result"


class BcutTranscriber:
    """必剪语音识别接口（免费在线转写）"""

    headers = {
        'User-Agent': 'Bilibili/1.0.0 (https://www.bilibili.com)',
        'Content-Type': 'application/json',
    }

    def __init__(self):
        self.session = requests.Session()
        self.task_id = None
        self.__etags: List[str] = []
        self.__in_boss_key: Optional[str] = None
        self.__resource_id: Optional[str] = None
        self.__upload_id: Optional[str] = None
        self.__upload_urls: List[str] = []
        self.__per_size: Optional[int] = None
        self.__clips: Optional[int] = None
        self.__download_url: Optional[str] = None

    def _upload(self, file_path: str) -> None:
        with open(file_path, 'rb') as f:
            file_binary = f.read()
        if not file_binary:
            raise ValueError("无法读取文件数据")

        payload = json.dumps({
            "type": 2, "name": "audio.mp3",
            "size": len(file_binary), "ResourceFileType": "mp3",
            "model_id": "8",
        })
        resp = self.session.post(API_REQ_UPLOAD, data=payload, headers=self.headers)
        resp.raise_for_status()
        resp_data = resp.json()["data"]

        self.__in_boss_key = resp_data["in_boss_key"]
        self.__resource_id = resp_data["resource_id"]
        self.__upload_id = resp_data["upload_id"]
        self.__upload_urls = resp_data["upload_urls"]
        self.__per_size = resp_data["per_size"]
        self.__clips = len(resp_data["upload_urls"])
        logger.info(f"申请上传成功, {self.__clips}分片")

        for clip in range(self.__clips):
            start_range = clip * self.__per_size
            end_range = min((clip + 1) * self.__per_size, len(file_binary))
            resp = self.session.put(
                self.__upload_urls[clip],
                data=file_binary[start_range:end_range],
                headers={'Content-Type': 'application/octet-stream'},
            )
            resp.raise_for_status()
            self.__etags.append(resp.headers.get("Etag", "").strip('"'))

        data = json.dumps({
            "InBossKey": self.__in_boss_key,
            "ResourceId": self.__resource_id,
            "Etags": ",".join(self.__etags),
            "UploadId": self.__upload_id,
            "model_id": "8",
        })
        resp = self.session.post(API_COMMIT_UPLOAD, data=data, headers=self.headers)
        resp.raise_for_status()
        resp = resp.json()
        if resp.get("code") != 0:
            raise Exception(f"上传提交失败: {resp.get('message', '未知错误')}")
        self.__download_url = resp["data"]["download_url"]

    def _create_task(self) -> str:
        resp = self.session.post(
            API_CREATE_TASK,
            json={"resource": self.__download_url, "model_id": "8"},
            headers=self.headers,
        )
        resp.raise_for_status()
        resp = resp.json()
        if resp.get("code") != 0:
            raise Exception(f"创建任务失败: {resp.get('message', '未知错误')}")
        self.task_id = resp["data"]["task_id"]
        return self.task_id

    def _query_result(self) -> dict:
        resp = self.session.get(
            API_QUERY_RESULT,
            params={"model_id": 7, "task_id": self.task_id},
            headers=self.headers,
        )
        resp.raise_for_status()
        resp = resp.json()
        if resp.get("code") != 0:
            raise Exception(f"查询结果失败: {resp.get('message', '未知错误')}")
        return resp["data"]

    def transcript(self, file_path: str) -> TranscriptResult:
        try:
            logger.info(f"开始处理文件: {file_path}")
            self.__etags = []
            self._upload(file_path)
            self._create_task()

            task_resp = None
            for i in range(500):
                task_resp = self._query_result()
                if task_resp["state"] == 4:
                    break
                elif task_resp["state"] == 3:
                    raise Exception(f"转写任务失败")
                if i % 10 == 0:
                    logger.info(f"转录进行中... {i}/500")
                time.sleep(1)

            if not task_resp or task_resp["state"] != 4:
                raise Exception("转写超时")

            result_json = json.loads(task_resp["result"])
            segments = []
            full_text = ""
            for u in result_json.get("utterances", []):
                text = u.get("transcript", "").strip()
                start_time = float(u.get("start_time", 0)) / 1000.0
                end_time = float(u.get("end_time", 0)) / 1000.0
                full_text += text + " "
                segments.append(TranscriptSegment(start=start_time, end=end_time, text=text))

            return TranscriptResult(
                language=result_json.get("language", "zh"),
                full_text=full_text.strip(),
                segments=segments,
                raw=result_json,
            )
        except Exception as e:
            logger.error(f"必剪ASR处理失败: {str(e)}")
            raise

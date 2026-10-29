"""豆包（火山方舟）图片生成客户端。

配置项（后台「接口配置 → 豆包生图」）：
    doubao_api_key   方舟 API Key
    doubao_base_url  默认 https://ark.cn-beijing.volces.com/api/v3
    doubao_model     图片模型 ID
    doubao_size      1024x1024 / 2K ...
    doubao_watermark 是否加水印
    doubao_timeout   生成超时

接口：
    POST {base}/images/generations
    Authorization: Bearer <key>
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from .http import HttpClient, HttpError
from .settings import Settings


class DoubaoError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DoubaoClient:
    def __init__(self, settings: Settings, http: HttpClient, data_dir: Path) -> None:
        self.settings = settings
        self.http = http
        self.save_dir = Path(data_dir) / "aigen"
        self.save_dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.doubao_api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.doubao_api_key}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        prompt: str,
        *,
        image: str | None = None,
        size: str | None = None,
        negative_prompt: str | None = None,
    ) -> Path:
        if not self.enabled:
            raise DoubaoError(
                "尚未配置豆包 API Key。请在后台「接口配置 → 豆包生图」填写。"
            )
        prompt = str(prompt or "").strip()
        if not prompt:
            raise DoubaoError("提示词不能为空")
        if len(prompt) > 2000:
            raise DoubaoError("提示词最多 2000 个字符")
        payload: dict[str, Any] = {
            "model": self.settings.doubao_model,
            "prompt": prompt,
            "size": size or self.settings.doubao_size,
            "response_format": "url",
            "watermark": self.settings.doubao_watermark,
        }
        if image:
            payload["image"] = str(image)
        if negative_prompt:
            payload["negative_prompt"] = str(negative_prompt)

        try:
            result = await self.http.request_json(
                "POST",
                f"{self.settings.doubao_base}/images/generations",
                json_body=payload,
                headers=self._headers(),
                timeout=self.settings.doubao_timeout,
                retries=0,
                source="doubao",
            )
        except HttpError as exc:
            message = "生图请求较多，请稍后再试。" if exc.status == 429 else "图片生成失败，请稍后再试。"
            raise DoubaoError(message) from exc

        body = result.data
        if not isinstance(body, dict):
            raise DoubaoError("豆包返回格式异常")
        if body.get("error"):
            raise DoubaoError("图片生成失败，请稍后再试。")
        items = body.get("data")
        if not isinstance(items, list) or not items:
            raise DoubaoError("豆包没有返回图片")
        first = items[0] if isinstance(items[0], dict) else {}
        if first.get("b64_json"):
            try:
                raw = base64.b64decode(first["b64_json"], validate=True)
            except Exception as exc:
                raise DoubaoError("豆包返回的 base64 图片无法解码") from exc
            return self._save(raw, "png")
        image_url = str(first.get("url") or "").strip()
        if not image_url:
            raise DoubaoError("豆包返回中没有图片地址")
        try:
            downloaded = await self.http.request_bytes(
                "GET",
                image_url,
                timeout=30,
                max_bytes=20 * 1024 * 1024,
                source="doubao-image",
            )
        except HttpError as exc:
            raise DoubaoError(f"下载生成图失败：{exc.message}") from exc
        suffix = "jpg"
        lowered = image_url.lower().split("?", 1)[0]
        for candidate in ("png", "jpeg", "jpg", "webp"):
            if lowered.endswith("." + candidate):
                suffix = "jpg" if candidate == "jpeg" else candidate
                break
        return self._save(downloaded.data, suffix)

    def _save(self, data: bytes, suffix: str) -> Path:
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise DoubaoError("生成图内容为空")
        path = self.save_dir / f"aigen_{time.time_ns()}.{suffix}"
        path.write_bytes(bytes(data))
        return path

    async def probe(self) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "message": "尚未配置豆包 API Key"}
        try:
            result = await self.http.request_json(
                "GET",
                f"{self.settings.doubao_base}/models",
                headers=self._headers(),
                timeout=15,
                retries=0,
                source="doubao-test",
            )
        except HttpError as exc:
            if exc.status == 401:
                return {"ok": False, "message": "豆包 API Key 无效（HTTP 401）"}
            if exc.status == 403:
                return {"ok": False, "message": "豆包 API Key 没有权限（HTTP 403）"}
            if exc.status == 404:
                return {
                    "ok": False,
                    "message": "接口可达，但 /models 不可用；请用一次「生图」验证 Key 和模型",
                }
            return {"ok": False, "message": f"豆包接口不可用：{exc.message}"}
        data = result.data
        count = len(data.get("data") or []) if isinstance(data, dict) else 0
        return {
            "ok": True,
            "message": f"豆包连接正常（可用模型 {count} 个）",
        }

import json
import httpx
from typing import AsyncGenerator, Dict, Any

from fastapi import HTTPException
from ..utils.config import settings
from ..models import ChatCompletionRequest, CompletionRequest


class NIMService:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    def _auth_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.nim_api_key}",
            "Content-Type": "application/json",
        }

    def _get_actual_model(self, requested_model: str) -> str:
        if requested_model in ["nvidia_nim", "gpt-4", "gpt-4o", "gpt-3.5-turbo"]:
            return settings.nim_model
        return requested_model or settings.nim_model

    async def get_chat_completion(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)
        response = await self.client.post(
            f"{settings.nim_base_url}/chat/completions",
            json=payload,
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"NVIDIA NIM error: {response.text}",
            )
        return response.json()

    async def stream_chat_completion(
        self, request: ChatCompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)
        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/chat/completions",
                json=payload,
                headers=self._auth_headers(),
            ) as response:
                if response.status_code != 200:
                    error_detail = await response.aread()
                    yield f"data: {json.dumps({'error': error_detail.decode()})}\n\n".encode()
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()

    async def get_completion(self, request: CompletionRequest) -> Dict[str, Any]:
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)
        response = await self.client.post(
            f"{settings.nim_base_url}/completions",
            json=payload,
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"NVIDIA NIM error: {response.text}",
            )
        return response.json()

    async def stream_completion(
        self, request: CompletionRequest
    ) -> AsyncGenerator[bytes, None]:
        payload = request.model_dump(exclude_none=True)
        payload["model"] = self._get_actual_model(request.model)
        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/completions",
                json=payload,
                headers=self._auth_headers(),
            ) as response:
                if response.status_code != 200:
                    error_detail = await response.aread()
                    yield f"data: {json.dumps({'error': error_detail.decode()})}\n\n".encode()
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()

    async def post_chat_completions_payload(
        self, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        p = dict(payload)
        p["model"] = self._get_actual_model(str(p.get("model", "")))
        p.pop("stream", None)
        response = await self.client.post(
            f"{settings.nim_base_url}/chat/completions",
            json=p,
            headers=self._auth_headers(),
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"NVIDIA NIM error: {response.text}",
            )
        return response.json()

    async def stream_chat_completions_payload(
        self, payload: Dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        p = dict(payload)
        p["model"] = self._get_actual_model(str(p.get("model", "")))
        p["stream"] = True
        try:
            async with self.client.stream(
                "POST",
                f"{settings.nim_base_url}/chat/completions",
                json=p,
                headers=self._auth_headers(),
            ) as response:
                if response.status_code != 200:
                    detail = await response.aread()
                    yield f"data: {json.dumps({'error': detail.decode()})}\n\n".encode()
                    return
                async for chunk in response.aiter_bytes():
                    yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n".encode()
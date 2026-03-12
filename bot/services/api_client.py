from __future__ import annotations

import aiohttp
import hashlib
import hmac
import time
from typing import Any, Dict


class ApiRequestError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"API error {status}: {detail}")
        self.status = status
        self.detail = detail


class ApiClient:
    def __init__(self, base_url: str, service_secret: str):
        self.base_url = base_url.rstrip("/")
        self.service_secret = service_secret

    def _signature(self, ts: int, method: str, path_qs: str) -> str:
        msg = f"{ts}.{method.upper()}.{path_qs}".encode("utf-8")
        return hmac.new(self.service_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def _service_headers(self, method: str, path_qs: str) -> Dict[str, str]:
        ts = int(time.time())
        sig = self._signature(ts, method, path_qs)
        return {
            "X-Service-Timestamp": str(ts),
            "X-Service-Signature": sig,
        }

    async def upload_document(
        self,
        telegram_user_id: int,
        chat_id: int,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> Dict[str, Any]:
        path_qs = "/v1/documents"
        url = f"{self.base_url}{path_qs}"

        form = aiohttp.FormData()
        form.add_field("telegram_user_id", str(telegram_user_id))
        form.add_field("chat_id", str(chat_id))
        form.add_field("file", data, filename=filename, content_type=content_type)

        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=form, headers=self._service_headers("POST", path_qs)) as r:
                if r.status >= 400:
                    try:
                        payload = await r.json()
                        detail = payload.get("detail") or str(payload)
                    except Exception:
                        detail = await r.text()
                    raise ApiRequestError(r.status, detail)
                return await r.json()

    async def pending_deliveries(self, limit: int = 20) -> Dict[str, Any]:
        path_qs = f"/v1/bot/pending-deliveries?limit={limit}"
        url = f"{self.base_url}{path_qs}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._service_headers("GET", path_qs)) as r:
                if r.status >= 400:
                    raise ApiRequestError(r.status, await r.text())
                return await r.json()

    async def ack_delivery(self, job_id: str) -> None:
        path_qs = f"/v1/bot/deliveries/{job_id}/ack"
        url = f"{self.base_url}{path_qs}"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=self._service_headers("POST", path_qs)) as r:
                if r.status >= 400:
                    raise ApiRequestError(r.status, await r.text())

    async def get_job(self, job_id: str, chat_id: int) -> Dict[str, Any]:
        path_qs = f"/v1/jobs/{job_id}?chat_id={chat_id}"
        url = f"{self.base_url}{path_qs}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._service_headers("GET", path_qs)) as r:
                if r.status >= 400:
                    raise ApiRequestError(r.status, await r.text())
                return await r.json()

    async def download_artifact(self, job_id: str, chat_id: int, artifact_id: str) -> bytes:
        path_qs = f"/v1/bot/jobs/{job_id}/artifacts/{artifact_id}/download?chat_id={chat_id}"
        url = f"{self.base_url}{path_qs}"
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=self._service_headers("GET", path_qs)) as r:
                if r.status >= 400:
                    raise ApiRequestError(r.status, await r.text())
                return await r.read()

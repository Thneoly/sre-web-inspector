from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import APIResponse, BrowserContext


@dataclass
class ReplayResult:
    name: str
    method: str
    url: str
    status: int
    headers: dict[str, str]
    data: Any
    output_path: Optional[Path]


class RequestReplayer:
    """
    复用 BrowserContext.request 主动请求接口。
    适合登录后复用 Cookie / 认证上下文直接请求后端 API。
    """

    def __init__(
        self,
        context: BrowserContext,
        *,
        output_dir: str | Path = "outputs/replay",
        save_response: bool = True,
    ) -> None:
        self.context = context
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.save_response = save_response

    async def get(
        self,
        url: str,
        *,
        name: str = "get_result",
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.get(url, params=params, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="GET", url=url, response=response)

    async def post_json(
        self,
        url: str,
        *,
        name: str = "post_json_result",
        data: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.post(url, data=data, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="POST", url=url, response=response)

    async def put_json(
        self,
        url: str,
        *,
        name: str = "put_json_result",
        data: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.put(url, data=data, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="PUT", url=url, response=response)

    async def patch_json(
        self,
        url: str,
        *,
        name: str = "patch_json_result",
        data: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.patch(url, data=data, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="PATCH", url=url, response=response)

    async def delete(
        self,
        url: str,
        *,
        name: str = "delete_result",
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.delete(url, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="DELETE", url=url, response=response)

    async def post_form(
        self,
        url: str,
        *,
        name: str = "post_form_result",
        form: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> ReplayResult:
        response = await self.context.request.post(url, form=form, headers=headers, timeout=timeout)
        return await self._build_result(name=name, method="POST", url=url, response=response)

    async def _build_result(
        self,
        *,
        name: str,
        method: str,
        url: str,
        response: APIResponse,
    ) -> ReplayResult:
        headers = dict(response.headers)
        data = await self._parse_response(response)

        output_path = None
        if self.save_response:
            output_path = self.output_dir / f"{name}.json"
            output_path.write_text(
                json.dumps({
                    "name": name,
                    "method": method,
                    "url": url,
                    "status": response.status,
                    "headers": headers,
                    "data": data,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return ReplayResult(
            name=name,
            method=method,
            url=url,
            status=response.status,
            headers=headers,
            data=data,
            output_path=output_path,
        )

    async def _parse_response(self, response: APIResponse) -> Any:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type.lower():
            try:
                return await response.json()
            except Exception:
                return await response.text()
        return await response.text()

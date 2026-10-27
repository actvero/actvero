import asyncio
import json
import ssl
from collections.abc import Mapping
from typing import Any

import httpx2
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.core.outbound import PinnedTransport, resolve
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.providers.connection import resolve_stored_connection
from app.modules.llm.schemas import ProviderView, UpstreamModel


def _caused_by(error: BaseException, kind: type[BaseException]) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, kind):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


class OpenAICompatible:
    info = ProviderView(
        id="openai-compatible",
        version=4,
        name="自定义 OpenAI 兼容",
        model_discovery=True,
        balance_query=False,
        allow_no_auth=True,
        member_inference=True,
        member_operations=[
            "chat",
            "embedding",
            "rerank",
            "image_generation",
            "speech",
            "transcription",
        ],
        test_operations=["chat", "embedding", "rerank", "image_generation", "speech"],
        default_api_prefix="/v1",
    )
    sdk_provider = "openai"

    def headers(self, key: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if key:
            headers["Authorization"] = "Bearer " + key
        return headers

    def entries(self, payload: dict[str, Any]) -> tuple[list[Any], bool]:
        return payload["data"], payload.get("has_more") is True

    def model_id(self, item: dict[str, Any]) -> str:
        value = item["id"]
        if not isinstance(value, str):
            raise ValueError("Invalid model ID")
        return value

    def first_page(self, url: str) -> dict[str, str | int]:
        return {}

    def next_page(
        self, payload: dict[str, Any], params: dict[str, str | int]
    ) -> dict[str, str | int] | None:
        # A generic compatible endpoint has no standard pagination contract.
        # Native adapters supply their documented cursor/page parameters.
        return None

    async def list_models(
        self,
        base_url: str,
        key: str | None,
        timeout: int,
        settings: Settings,
        *,
        connection: Mapping[str, Any] | None = None,
    ) -> ModelListing:
        if not self.info.model_discovery:
            raise HTTPException(422, "此预设暂未接入模型目录，请手动登记上游模型 ID 后测试")
        directory = resolve_stored_connection(self.info.id, base_url, connection, operations=())
        if directory.directory_url is None:
            raise HTTPException(422, "此预设暂未接入模型目录，请手动登记上游模型 ID 后测试")
        transport = PinnedTransport(
            base_url,
            lambda url: resolve(
                url, settings.llm_allowed_private_origins, dns=settings.llm_public_dns
            ),
        )
        headers = self.headers(key)
        params = self.first_page(directory.directory_url)
        models: dict[str, UpstreamModel] = {}
        seen_pages: set[str] = set()
        total_bytes = 0
        try:
            async with asyncio.timeout(timeout):
                async with httpx2.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx2.Timeout(timeout, connect=min(10, timeout)),
                ) as client:
                    for page in range(10):
                        signature = json.dumps(params, sort_keys=True)
                        if signature in seen_pages:
                            raise ValueError("Repeated directory cursor")
                        seen_pages.add(signature)
                        async with client.stream(
                            directory.directory_method,
                            directory.directory_url,
                            headers=headers,
                            params=params or None,
                        ) as res:
                            if res.status_code != 200:
                                messages = {
                                    401: "上游拒绝认证，请检查 API Key 是否属于当前供应商及产品",
                                    403: "上游拒绝读取模型目录，请检查账号权限",
                                    404: "上游模型目录接口返回 404，请核对渠道地址、产品和接口前缀",
                                    429: "上游请求限流，请稍后重试",
                                }
                                raise HTTPException(
                                    502,
                                    messages.get(
                                        res.status_code,
                                        f"模型目录请求失败（HTTP {res.status_code}）",
                                    ),
                                )
                            # Bound the whole fetch, including all pages; never decompress
                            # an arbitrarily large upstream response in memory.
                            if (
                                res.headers.get("content-encoding", "identity").lower()
                                != "identity"
                            ):
                                raise HTTPException(502, "上游未按请求返回未压缩目录")
                            data = bytearray()
                            async for chunk in res.aiter_raw():
                                total_bytes += len(chunk)
                                if total_bytes > 2_000_000:
                                    raise HTTPException(502, "模型目录超过 2 MB，未完成获取")
                                data.extend(chunk)
                            payload = json.loads(data)
                        if not isinstance(payload, dict):
                            raise ValueError("Invalid directory")
                        entries, partial = self.entries(payload)
                        if not isinstance(entries, list):
                            raise ValueError("Invalid directory")
                        for item in entries:
                            if not isinstance(item, dict):
                                raise ValueError("Invalid model")
                            model = UpstreamModel.model_validate({"id": self.model_id(item)})
                            if key and key in model.id:
                                raise ValueError("Credential echoed")
                            models[model.id] = model
                        if len(models) > 1000:
                            raise HTTPException(502, "模型目录超过 1000 项，未完成获取")
                        next_params = self.next_page(payload, params) if partial else None
                        if not next_params or page == 9 or len(models) == 1000:
                            return ModelListing(list(models.values()), partial)
                        # Only bounded query parameters are accepted, never upstream URLs.
                        if any(
                            not isinstance(v, (str, int))
                            or len(str(v)) > 2000
                            or (key and key in str(v))
                            for v in next_params.values()
                        ):
                            raise ValueError("Invalid directory cursor")
                        params = next_params
            raise ValueError("Invalid directory pagination")
        except httpx2.ConnectTimeout as exc:
            raise HTTPException(502, "连接模型目录超时，请检查部署网络、DNS 和上游地址") from exc
        except httpx2.ReadTimeout as exc:
            raise HTTPException(502, "等待模型目录响应超时，请检查上游服务或调整超时时间") from exc
        except (httpx2.TimeoutException, TimeoutError) as exc:
            raise HTTPException(502, "读取模型目录超时，请检查网络或调整超时时间") from exc
        except httpx2.HTTPError as exc:
            if _caused_by(exc, ssl.SSLCertVerificationError):
                detail = "模型目录 TLS 证书验证失败，请检查上游证书、服务域名和部署 DNS"
            elif _caused_by(exc, ssl.SSLError):
                detail = "模型目录 TLS 握手或连接中断，请检查部署 DNS、网络和上游服务"
            elif isinstance(exc, (httpx2.ConnectError, httpx2.ReadError, httpx2.WriteError)):
                detail = "模型目录连接失败或中断，请检查上游地址、部署 DNS 和网络"
            else:
                detail = "无法读取模型目录，请检查地址、TLS 和部署网络"
            raise HTTPException(502, detail) from exc
        except (ValueError, TypeError, KeyError, ValidationError) as exc:
            raise HTTPException(502, "上游返回了无效的模型目录，可改为手动登记") from exc

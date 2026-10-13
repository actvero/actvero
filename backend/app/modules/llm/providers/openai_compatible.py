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
        try:
            async with asyncio.timeout(timeout):
                async with httpx2.AsyncClient(
                    transport=transport,
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx2.Timeout(timeout, connect=min(10, timeout)),
                ) as client:
                    async with client.stream(
                        directory.directory_method, directory.directory_url, headers=headers
                    ) as res:
                        if res.status_code != 200:
                            messages = {
                                401: "上游拒绝认证，请检查 API Key",
                                403: "上游拒绝读取模型目录，请检查账号权限",
                                404: "上游未提供模型目录，请核对 Base URL 或手动登记模型",
                                429: "上游请求限流，请稍后重试",
                            }
                            raise HTTPException(
                                502,
                                messages.get(
                                    res.status_code, f"模型目录请求失败（HTTP {res.status_code}）"
                                ),
                            )
                        # Enforce the requested identity encoding before decoding; even a
                        # small compressed chunk could otherwise allocate an enormous body.
                        if res.headers.get("content-encoding", "identity").lower() != "identity":
                            raise HTTPException(502, "上游未按请求返回未压缩目录，请手动登记模型")
                        data = bytearray()
                        async for chunk in res.aiter_raw():
                            data.extend(chunk)
                            if len(data) > 2_000_000:
                                raise HTTPException(502, "模型目录超过 2 MB，请手动登记模型")
                        payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("Invalid directory")
            entries, partial = self.entries(payload)
            if not isinstance(entries, list):
                raise ValueError("Invalid directory")
            if len(entries) > 1000:
                raise HTTPException(502, "模型目录超过 1000 项，请手动登记所需模型")
            models: dict[str, UpstreamModel] = {}
            for item in entries:
                if not isinstance(item, dict):
                    raise ValueError("Invalid model")
                model = UpstreamModel.model_validate({"id": self.model_id(item)})
                # A misconfigured upstream must not echo our credential into the UI.
                if key and key in model.id:
                    raise ValueError("Credential echoed")
                models[model.id] = model
            return ModelListing(list(models.values()), partial)
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

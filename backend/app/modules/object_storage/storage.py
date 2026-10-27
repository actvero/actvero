"""S3 control operations run outside the API event loop; credentials stay server-side."""

import asyncio
from typing import Any, BinaryIO

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from fastapi import HTTPException

from app.modules.object_storage.models import ObjectStorage as ClientStorage


class ObjectStore:
    def __init__(self, profile: ClientStorage, credentials: dict[str, Any]) -> None:
        self.bucket = profile.bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=profile.endpoint,
            region_name=profile.region,
            aws_access_key_id=credentials["access_key"],
            aws_secret_access_key=credentials["secret_key"],
            config=Config(
                signature_version="s3v4",
                connect_timeout=10,
                read_timeout=45,
                retries={"total_max_attempts": 1},
                # Compatible stores may retain AWS's optional trailer encoding as object metadata.
                request_checksum_calculation="when_required",
                s3={"addressing_style": "path" if profile.path_style else "virtual"},
            ),
        )

    async def call(self, name: str, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(getattr(self.client, name), Bucket=self.bucket, **kwargs)
        except (BotoCoreError, ClientError):
            # Provider messages can contain signed URLs, request headers or access keys.
            raise HTTPException(502, "对象存储请求未确认，请检查连接并回查上传任务") from None

    async def start(self, key: str) -> str:
        result = await self.call(
            "create_multipart_upload", Key=key, ContentType="application/octet-stream"
        )
        return str(result["UploadId"])

    async def sign(self, key: str, upload_id: str, number: int, size: int) -> str:
        return str(
            await asyncio.to_thread(
                self.client.generate_presigned_url,
                "upload_part",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "UploadId": upload_id,
                    "PartNumber": number,
                    "ContentLength": size,
                },
                ExpiresIn=900,
                HttpMethod="PUT",
            )
        )

    async def sign_get(self, key: str) -> str:
        try:
            return str(
                await asyncio.to_thread(
                    self.client.generate_presigned_url,
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": key},
                    ExpiresIn=3600,
                    HttpMethod="GET",
                )
            )
        except (BotoCoreError, ClientError):
            raise HTTPException(502, "无法生成下载凭据，请稍后重试") from None

    async def parts(self, key: str, upload_id: str) -> dict[int, tuple[str, int]]:
        result: dict[int, tuple[str, int]] = {}
        marker = 0
        while True:
            page = await self.call(
                "list_parts", Key=key, UploadId=upload_id, PartNumberMarker=marker
            )
            result.update(
                {
                    int(p["PartNumber"]): (str(p["ETag"]), int(p["Size"]))
                    for p in page.get("Parts", [])
                }
            )
            if not page.get("IsTruncated"):
                return result
            marker = int(page["NextPartNumberMarker"])

    async def head(self, key: str) -> dict[str, Any] | None:
        try:
            result: dict[str, Any] = await asyncio.to_thread(
                self.client.head_object, Bucket=self.bucket, Key=key
            )
            return result
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise HTTPException(502, "无法核对存储对象，请稍后回查") from None
        except BotoCoreError:
            raise HTTPException(502, "无法核对存储对象，请稍后回查") from None

    async def complete(self, key: str, upload_id: str, parts: dict[str, str]) -> None:
        await self.call(
            "complete_multipart_upload",
            Key=key,
            UploadId=upload_id,
            MultipartUpload={
                "Parts": [
                    {"PartNumber": int(n), "ETag": etag}
                    for n, etag in sorted(parts.items(), key=lambda p: int(p[0]))
                ]
            },
        )

    async def abort(self, key: str, upload_id: str) -> None:
        try:
            await asyncio.to_thread(
                self.client.abort_multipart_upload,
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
            )
        except ClientError as error:
            if str(error.response.get("Error", {}).get("Code")) == "NoSuchUpload":
                return
            raise HTTPException(502, "取消上传未确认，请稍后回查") from None
        except BotoCoreError:
            raise HTTPException(502, "取消上传未确认，请稍后回查") from None

    async def put(self, key: str, file: BinaryIO, size: int) -> None:
        await self.call(
            "put_object",
            Key=key,
            Body=file,
            ContentLength=size,
            ContentType="application/octet-stream",
        )

    async def put_large(self, key: str, file: BinaryIO) -> None:
        try:
            await asyncio.to_thread(
                self.client.upload_fileobj,
                file,
                self.bucket,
                key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
        except (BotoCoreError, ClientError):
            raise HTTPException(502, "转存写入未确认，请回查任务后重试") from None


__all__ = ["BotoCoreError", "ClientError"]

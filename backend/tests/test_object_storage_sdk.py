"""Exercise the signed SDK wire requests without contacting a storage provider."""

import io
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.awsrequest import AWSResponse

from app.modules.object_storage.models import ObjectStorage
from app.modules.object_storage.storage import ObjectStore

pytestmark = pytest.mark.asyncio


class EmptyBody:
    def __init__(self, body=b""):
        self.body = body

    def stream(self, amt=None, decode_content=False):
        yield self.body


@pytest.mark.parametrize("operation", ["put", "part", "managed_multipart"])
async def test_uploads_preserve_identity_bytes(monkeypatch, operation):
    profile = ObjectStorage(
        endpoint="https://s3.example.com",
        region="us-east-1",
        bucket="test-bucket",
        path_style=False,
    )
    store = ObjectStore(profile, {"access_key": "test-access", "secret_key": "test-secret"})
    payload = b"installer-fixture\x00\xff" * (500_000 if operation == "managed_multipart" else 1)
    uploaded = {}

    def send(request):
        query = parse_qs(urlsplit(request.url).query)
        body = request.body
        if request.method == "PUT":
            wire = body.read() if hasattr(body, "read") else body
            if operation != "managed_multipart":
                assert wire == payload
            assert "aws-chunked" not in str(request.headers.get("Content-Encoding", ""))
            assert request.headers.get("Transfer-Encoding") is None
            assert int(request.headers["Content-Length"]) == len(wire)
            uploaded[int(query.get("partNumber", [1])[0])] = wire
            return AWSResponse(request.url, 200, {"ETag": '"fixture"'}, EmptyBody())
        if "uploadId" in query:
            xml = (
                b"<CompleteMultipartUploadResult><ETag>fixture</ETag>"
                b"</CompleteMultipartUploadResult>"
            )
        else:
            xml = (
                b"<InitiateMultipartUploadResult><UploadId>upload</UploadId>"
                b"</InitiateMultipartUploadResult>"
            )
        return AWSResponse(request.url, 200, {}, EmptyBody(xml))

    monkeypatch.setattr(store.client._endpoint.http_session, "send", send)
    try:
        if operation == "put":
            await store.put("installer", io.BytesIO(payload), len(payload))
        elif operation == "part":
            await store.call(
                "upload_part",
                Key="installer",
                UploadId="upload",
                PartNumber=1,
                Body=io.BytesIO(payload),
                ContentLength=len(payload),
            )
        else:
            await store.put_large("installer", io.BytesIO(payload))
        assert b"".join(uploaded[n] for n in sorted(uploaded)) == payload
        assert len(uploaded) == (2 if operation == "managed_multipart" else 1)
    finally:
        store.client.close()

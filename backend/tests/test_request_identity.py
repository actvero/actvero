"""Member request identities are stable, scoped, and safe to persist."""

import re
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import EmbeddingInput, RerankInput
from app.modules.llm.request_identity import fingerprints_equal, request_fingerprint


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, session_encryption_key=Fernet.generate_key().decode())


@pytest.fixture
def scope() -> tuple:
    return uuid4(), uuid4(), uuid4()


def chat(**overrides: object) -> ChatInput:
    return ChatInput.model_validate(
        {
            "model": "shared-model",
            "messages": [{"role": "user", "content": "private input"}],
            **overrides,
        }
    )


def test_canonical_defaults_and_mapping_order(settings: Settings, scope: tuple) -> None:
    tenant, member, model = scope
    first = ChatInput.model_validate(
        {
            "model": "shared-model",
            "messages": [{"content": "private input", "role": "user"}],
            "tools": [
                {
                    "function": {
                        "parameters": {
                            "properties": {"z": {"type": "string"}, "a": {"type": "integer"}}
                        },
                        "name": "lookup",
                    },
                    "type": "function",
                }
            ],
        }
    )
    second = ChatInput.model_validate(
        {
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {
                            "properties": {"a": {"type": "integer"}, "z": {"type": "string"}}
                        },
                    },
                }
            ],
            "messages": [{"role": "user", "content": "private input"}],
            "model": "shared-model",
            "stream": False,
            "n": 1,
            "stream_options": None,
        }
    )
    digest = request_fingerprint(settings, tenant, member, model, "chat", first)
    assert digest == request_fingerprint(settings, tenant, member, model, "chat", second)
    assert re.fullmatch(r"v1:[0-9a-f]{64}", digest)
    assert "private input" not in digest
    assert settings.session_encryption_key is not None
    assert settings.session_encryption_key.get_secret_value() not in digest
    assert fingerprints_equal(digest, digest)


def test_request_content_parameters_and_array_order_change_digest(
    settings: Settings, scope: tuple
) -> None:
    tenant, member, model = scope

    def digest(body: ChatInput) -> str:
        return request_fingerprint(settings, tenant, member, model, "chat", body)

    base = digest(chat())
    assert digest(chat(messages=[{"role": "user", "content": "changed"}])) != base
    assert digest(chat(max_tokens=8)) != base
    assert digest(chat(stream=True)) != base
    assert digest(chat(model="other-model")) != base
    ordered = chat(
        messages=[
            {"role": "system", "content": "first"},
            {"role": "user", "content": "second"},
        ]
    )
    reversed_messages = chat(
        messages=[
            {"role": "user", "content": "second"},
            {"role": "system", "content": "first"},
        ]
    )
    assert digest(ordered) != digest(reversed_messages)
    tools = [
        {"type": "function", "function": {"name": "one"}},
        {"type": "function", "function": {"name": "two"}},
    ]
    assert digest(chat(tools=tools)) != digest(chat(tools=list(reversed(tools))))


def test_member_model_tenant_and_operation_scope(settings: Settings, scope: tuple) -> None:
    tenant, member, model = scope
    body = chat()
    original = request_fingerprint(settings, tenant, member, model, "chat", body)
    assert request_fingerprint(settings, uuid4(), member, model, "chat", body) != original
    assert request_fingerprint(settings, tenant, uuid4(), model, "chat", body) != original
    assert request_fingerprint(settings, tenant, member, uuid4(), "chat", body) != original
    assert not fingerprints_equal(original, original[:-1] + ("0" if original[-1] != "0" else "1"))
    with pytest.raises(ValueError, match="operation and body"):
        request_fingerprint(settings, tenant, member, model, "embedding", body)
    with pytest.raises(ValueError, match="operation and body"):
        request_fingerprint(settings, tenant, member, model, "invalid", body)  # type: ignore[arg-type]


def test_all_supported_operations_and_secret_rotation(settings: Settings, scope: tuple) -> None:
    tenant, member, model = scope
    requests = [
        ("embedding", EmbeddingInput.model_validate({"model": "m", "input": ["a", "b"]})),
        ("rerank", RerankInput.model_validate({"model": "m", "query": "q", "documents": ["a"]})),
        ("image_generation", ImageInput.model_validate({"model": "m", "prompt": "draw"})),
    ]
    digests = {
        request_fingerprint(settings, tenant, member, model, operation, body)
        for operation, body in requests
    }
    assert len(digests) == 3
    other_key = Settings(_env_file=None, session_encryption_key=Fernet.generate_key().decode())
    for operation, body in requests:
        assert request_fingerprint(settings, tenant, member, model, operation, body) != (
            request_fingerprint(other_key, tenant, member, model, operation, body)
        )


def test_invalid_float_and_missing_key_are_rejected(settings: Settings, scope: tuple) -> None:
    tenant, member, model = scope
    with pytest.raises(ValueError):
        chat(temperature=float("nan"))
    nested_nan = chat(
        tools=[
            {
                "type": "function",
                "function": {"name": "lookup", "parameters": {"threshold": float("nan")}},
            }
        ]
    )
    with pytest.raises(ValueError):
        request_fingerprint(settings, tenant, member, model, "chat", nested_nan)
    no_key = Settings(_env_file=None, session_encryption_key=None)
    with pytest.raises(ValueError, match="key unavailable"):
        request_fingerprint(no_key, tenant, member, model, "chat", chat())

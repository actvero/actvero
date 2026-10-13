import json
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest

from actvero_cli.client import Client
from actvero_cli.commands import parser
from actvero_cli.config import canonical_server
from actvero_cli.errors import CliError


class Store:
    def __init__(self):
        self.blob = {}
        self.fail_save = False

    @contextmanager
    def lock(self):
        yield

    def load(self):
        return json.loads(json.dumps(self.blob))

    def save(self, blob):
        if self.fail_save:
            raise CliError("secure_store_unavailable", "test store unavailable")
        self.blob = json.loads(json.dumps(blob))

    def clear(self):
        self.blob = {}


def tokens(access="initial", refresh="initial", expires=300):
    return {
        "scope": "management:read",
        "access_token": "avm_access_" + access,
        "refresh_token": "avm_refresh_" + refresh,
        "expires_in": expires,
        "session_id": str(uuid4()),
    }


@pytest.mark.parametrize(
    "value",
    [
        "http://example.com",
        "https://u:p@example.com",
        "https://example.com?token=x",
        "https://example.com/#x",
        "https://example.com/a/../b",
        "https://example.com/%2e%2e",
        "https://example.com\\evil",
        "https://example.com:bad",
    ],
)
def test_invalid_servers_never_used(value):
    with pytest.raises(CliError):
        canonical_server(value)


def test_canonical_server_keeps_instance_address():
    assert canonical_server("HTTPS://EXAMPLE.COM:443/app/") == "https://example.com/app"
    assert canonical_server("http://127.0.0.1:5194/") == "http://127.0.0.1:5194"


def test_no_implicit_org_or_unimplemented_write_commands():
    for args in (
        ["channels", "list"],
        ["channels", "show", "--id", str(uuid4())],
        ["models", "create"],
    ):
        with pytest.raises(SystemExit):
            parser().parse_args(args)
    one, two = str(uuid4()), str(uuid4())
    assert parser().parse_args(["channels", "list", "--org", one]).org == one
    assert parser().parse_args(["channels", "list", "--org", two]).org == two


def test_lost_refresh_response_reuses_durable_request_after_restart():
    store, requests = Store(), []
    rotated = tokens("new", "new")

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/refresh"):
            body = json.loads(request.content)
            assert store.blob["pending"] == {
                "request_id": body["request_id"],
                "refresh_token": body["refresh_token"],
            }
            if len([r for r in requests if r.url.path.endswith("/refresh")]) == 1:
                raise httpx.ReadError("lost response")
            return httpx.Response(200, json={**rotated, "refresh_request_id": body["request_id"]})
        return httpx.Response(200, json={"items": []})

    first = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    first.save_login(tokens(expires=0), "instance-one")
    with pytest.raises(CliError):
        first.get("/organizations")
    pending = store.blob["pending"].copy()
    restarted = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    restarted.get("/organizations")
    refreshes = [json.loads(r.content) for r in requests if r.url.path.endswith("/refresh")]
    assert len(refreshes) == 2 and refreshes[0] == refreshes[1]
    assert refreshes[1]["request_id"] == pending["request_id"]
    assert store.blob["tokens"]["refresh_token"] == rotated["refresh_token"]
    assert store.blob["pending"] is None and store.blob["ack"] is None


def test_save_failure_before_rotation_prevents_any_network_request():
    store, sent = Store(), []
    client = Client(
        "https://platform.test",
        store,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))
        ),
    )
    client.save_login(tokens(expires=0), "one")
    store.fail_save = True
    with pytest.raises(CliError):
        client.get("/organizations")
    assert not sent


def test_save_failure_after_rotation_keeps_old_journal_and_never_acknowledges():
    store, sent = Store(), []

    def handler(request):
        sent.append(request)
        store.fail_save = True
        return httpx.Response(
            200, json={**tokens("new", "new"), "refresh_request_id": str(uuid4())}
        )

    client = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.save_login(tokens(expires=0), "one")
    with pytest.raises(CliError):
        client.get("/organizations")
    assert len(sent) == 1 and sent[0].url.path.endswith("/refresh")
    assert store.blob["pending"] is not None
    assert store.blob["tokens"]["refresh_token"] == "avm_refresh_initial"


def test_403_never_refreshes_or_changes_organization():
    store, sent = Store(), []

    def handler(request):
        sent.append(request)
        return httpx.Response(
            403, json={"error": {"code": "administrator_required", "message": "denied"}}
        )

    client = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.save_login(tokens(), "one")
    org = str(uuid4())
    with pytest.raises(CliError) as exc:
        client.get("/organizations/" + org + "/channels")
    assert exc.value.status == 403 and len(sent) == 1
    assert org in str(sent[0].url) and store.blob["pending"] is None


def test_logout_network_failure_blocks_business_then_same_session_can_logout():
    store, sent = Store(), []

    def handler(request):
        sent.append(request)
        if len(sent) == 1:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json={"message": "done"})

    client = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.save_login(tokens(), "one")
    with pytest.raises(CliError):
        client.logout()
    with pytest.raises(CliError) as exc:
        client.get("/organizations")
    assert exc.value.code == "logout_pending" and len(sent) == 1
    client.logout()
    assert not store.blob and len(sent) == 2


def test_expired_access_retries_get_only_once_with_rotated_credential():
    store, sent = Store(), []

    def handler(request):
        sent.append(request)
        if request.url.path.endswith("/refresh"):
            body = json.loads(request.content)
            return httpx.Response(
                200, json={**tokens("new", "new"), "refresh_request_id": body["request_id"]}
            )
        if request.headers.get("authorization") == "Bearer avm_access_initial":
            return httpx.Response(401, json={"error": {"code": "access_expired"}})
        return httpx.Response(200, json={"user": {"id": "one"}})

    client = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    client.save_login(tokens(), "one")
    assert client.get("/me")["user"]["id"] == "one"
    assert [str(r.url).split("/")[-1] for r in sent] == ["me", "refresh", "acknowledge", "me"]

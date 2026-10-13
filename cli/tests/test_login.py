import json
import threading
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import pytest
from test_cli import Store, tokens

from actvero_cli.client import Client
from actvero_cli.errors import CliError
from actvero_cli.login import Loopback, login


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "foreign"},
        {"iss": "https://foreign.test"},
        {"code": ""},
        {"code": ["one", "two"]},
        {"error": "denied"},
    ],
)
def test_loopback_rejects_foreign_duplicate_empty_and_ambiguous_callback(changes):
    callback = Loopback()
    callback.state, callback.issuer = "expected", "https://issuer.test"
    try:
        query = {"state": callback.state, "iss": callback.issuer, "code": "one", **changes}
        thread = threading.Thread(target=callback.server.handle_request)
        thread.start()
        response = httpx.get(callback.redirect_uri + "?" + urlencode(query, doseq=True))
        thread.join(timeout=3)
        assert response.status_code == 400 and callback.result is None
    finally:
        callback.close()


def test_loopback_accepts_one_valid_code_and_denial_never_returns_code():
    for result in ({"code": "valid"}, {"error": "access_denied"}):
        callback = Loopback()
        callback.state, callback.issuer = "expected", "https://issuer.test"
        try:
            thread = threading.Thread(target=callback.server.handle_request)
            thread.start()
            response = httpx.get(
                callback.redirect_uri
                + "?"
                + urlencode({"state": callback.state, "iss": callback.issuer, **result})
            )
            thread.join(timeout=3)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            if "error" in result:
                with pytest.raises(CliError) as exc:
                    callback.wait(timeout=0)
                assert exc.value.code == "login_cancelled"
            else:
                assert callback.wait(timeout=0)["code"] == "valid"
                thread = threading.Thread(target=callback.server.handle_request)
                thread.start()
                repeated = httpx.get(
                    callback.redirect_uri
                    + "?"
                    + urlencode({"state": callback.state, "iss": callback.issuer, **result})
                )
                thread.join(timeout=3)
                assert repeated.status_code == 400
        finally:
            callback.close()


def test_refresh_expired_cached_result_has_bounded_successor_rotation():
    store, sent = Store(), []

    def handler(request):
        sent.append(request)
        if request.url.path.endswith("/refresh"):
            body = json.loads(request.content)
            return httpx.Response(
                200, json={**tokens(expires=0), "refresh_request_id": body["request_id"]}
            )
        return httpx.Response(200, json={})

    api = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    api.save_login(tokens(expires=0), "instance")
    with pytest.raises(CliError) as exc:
        api.get("/organizations")
    assert exc.value.code == "invalid_response"
    assert len([r for r in sent if r.url.path.endswith("/refresh")]) == 2
    assert not any(r.method == "GET" for r in sent)
    assert store.blob["pending"] is None


def test_pending_login_cancel_must_succeed_before_any_new_authorization():
    store, sent = Store(), []
    proof = {"attempt_id": str(uuid4()), "state": "state", "code_verifier": "proof"}
    store.save({"login_pending": proof})

    def handler(request):
        sent.append(request)
        assert request.url.path.endswith("/login/cancel")
        assert json.loads(request.content) == proof
        raise httpx.ReadError("lost cancellation")

    api = Client(
        "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(CliError):
        login(api)
    assert len(sent) == 1 and store.blob["login_pending"] == proof


def test_browser_failure_cancels_saved_attempt_or_preserves_recovery(monkeypatch):
    opened = []

    def browser(url):
        opened.append(url)
        return False

    monkeypatch.setattr("actvero_cli.login.webbrowser.open", browser)
    for cancellation_fails in (False, True):
        store, sent = Store(), []
        attempt = str(uuid4())

        def handler(
            request, sent=sent, attempt=attempt, store=store, cancellation_fails=cancellation_fails
        ):
            sent.append(request)
            if request.url.path.endswith("/metadata"):
                return httpx.Response(
                    200,
                    json={
                        "contract_version": 1,
                        "scope": "management:read",
                        "instance_id": "instance",
                        "issuer": "https://issuer.test/realm",
                    },
                )
            if request.url.path.endswith("/start"):
                return httpx.Response(
                    200,
                    json={
                        "attempt_id": attempt,
                        "state": "one-state",
                        "issuer": "https://issuer.test/realm",
                        "authorization_url": "https://issuer.test/realm/auth",
                    },
                )
            assert request.url.path.endswith("/cancel")
            assert store.blob["login_pending"] == json.loads(request.content)
            if cancellation_fails:
                raise httpx.ReadError("lost cancel")
            return httpx.Response(200, json={})

        api = Client(
            "https://platform.test", store, httpx.Client(transport=httpx.MockTransport(handler))
        )
        with pytest.raises(CliError) as exc:
            login(api)
        assert exc.value.code == "browser_unavailable"
        assert len(sent) == 3
        assert bool(store.blob.get("login_pending")) == cancellation_fails
    assert len(opened) == 2


def test_existing_login_is_not_overwritten_and_store_failure_prevents_authorization():
    store, sent = Store(), []
    api = Client(
        "https://platform.test",
        store,
        httpx.Client(
            transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={}))
        ),
    )
    api.save_login(tokens(), "instance")
    original = store.load()
    with pytest.raises(CliError) as exc:
        login(api)
    assert exc.value.code == "already_logged_in" and store.load() == original
    store.clear()
    store.fail_save = True
    with pytest.raises(CliError) as exc:
        login(api)
    assert exc.value.code == "secure_store_unavailable" and not sent


def test_plaintext_keyring_backend_is_rejected(monkeypatch):
    from actvero_cli.store import CredentialStore

    class Plaintext:
        pass

    monkeypatch.setattr("actvero_cli.store.keyring.get_keyring", lambda: Plaintext())
    with pytest.raises(CliError) as exc:
        CredentialStore("https://platform.test")
    assert exc.value.code == "secure_store_unavailable"

from pathlib import Path

from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.dependencies import require_identity
from app.core.config import Settings
from app.main import create_app


def test_missing_database_does_not_report_ready(tmp_path: Path) -> None:
    app = create_app(Settings(database_url=None, static_dir=tmp_path, _env_file=None))
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        result = client.get("/api/v1/ready")
        assert result.status_code == 503
        assert result.json()["database"] == "unavailable"


def test_spa_fallback_does_not_hide_missing_api_or_assets(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>Actvero</html>")
    app = create_app(Settings(database_url=None, static_dir=tmp_path, _env_file=None))
    with TestClient(app) as client:
        assert client.get("/members").status_code == 200
        assert client.get("/api/v1/members").status_code == 404
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get("/brand/missing.svg").status_code == 404


def test_unconfigured_identity_fails_closed(tmp_path: Path) -> None:
    app = create_app(Settings(database_url=None, static_dir=tmp_path, _env_file=None))

    @app.get("/api/test-protected", dependencies=[Depends(require_identity)])
    async def protected() -> dict[str, str]:
        return {"private": "data"}

    # Register ahead of the SPA catch-all for this test-only endpoint.
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        response = client.get("/api/test-protected")
        assert response.status_code == 503
        assert "private" not in response.json()

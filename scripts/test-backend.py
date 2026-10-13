"""Run real PostgreSQL tests in disposable schemas, never application tables."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
settings = Settings()
if not settings.database_url:
    raise SystemExit("请先配置本项目数据库")
env = dict(os.environ, ACTVERO_TEST_DATABASE_URL=settings.database_url.get_secret_value())
raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q"], env=env))

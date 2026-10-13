"""Export the actual FastAPI schema without starting a server or connecting to PostgreSQL."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.main import create_app  # noqa: E402

content = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
target = root / "docs/api/openapi.json"
if "--check" in sys.argv:
    if not target.exists() or target.read_text() != content:
        raise SystemExit("OpenAPI 快照过期，请执行 make generate-api")
else:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    print("已导出当前已实现的接口。")

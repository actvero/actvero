"""Preview and explicitly relocate issuer mappings. Stop app and back up DB first."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.core.config import Settings
from app.core.database import Database
from app.modules.auth.issuer_migration import prepare, relocate
from app.modules.auth.oidc import IdentityProvider


async def run(args):
    settings = Settings(_env_file=args.env_file)
    if args.issuer:
        settings.oidc_issuer = args.issuer
    if args.internal_url:
        settings.oidc_internal_url = args.internal_url
    # Revalidate overrides instead of bypassing origin/TLS rules.
    settings = Settings(_env_file=None, **settings.model_dump())
    database = Database(settings)
    try:
        async with database.sessions() as db:
            provider = IdentityProvider(settings)
            if args.action == "prepare":
                manifest = await prepare(db, provider, args.target)
                fd = os.open(args.manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as handle:
                    json.dump(manifest, handle, indent=2)
                print(
                    json.dumps(
                        {
                            "status": "previewed",
                            "identities": len(manifest["identities"]),
                            "manifest": str(args.manifest),
                        }
                    )
                )
            else:
                manifest = json.loads(args.manifest.read_text())
                status = await relocate(db, provider, manifest)
                print(json.dumps({"status": status, "identities": len(manifest["identities"])}))
    finally:
        await database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "apply"])
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--target")
    parser.add_argument("--issuer")
    parser.add_argument("--internal-url")
    args = parser.parse_args()
    if args.action == "prepare" and not args.target:
        parser.error("prepare requires --target")
    try:
        asyncio.run(run(args))
    except Exception:
        # Upstream responses, DB DSNs and credential bodies must never be printed.
        print(
            "Issuer relocation refused or temporarily unavailable; configuration/data preserved.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

"""Batch credentials stay write-only; account hints only group rate limits."""

import base64
import binascii
import hashlib
import json


def account_hint(key: str) -> str:
    # JWT claims are unverified hints for cooldown grouping, never an identity
    # or permission assertion. MinerU alone validates the submitted credential.
    try:
        encoded = key.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if isinstance(claims, dict):
            subject = next((claims[k] for k in ("user_id", "sub", "uid") if claims.get(k)), None)
            if isinstance(subject, (str, int)):
                value = str(claims.get("iss", "")) + ":" + str(subject)
                return "account:" + hashlib.sha256(value.encode()).hexdigest()[:32]
    except (IndexError, ValueError, UnicodeError, binascii.Error):
        pass
    return "key:" + hashlib.sha256(key.encode()).hexdigest()[:32]

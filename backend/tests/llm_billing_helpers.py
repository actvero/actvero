"""Explicit test-only billing configuration; production has no implicit rates or limits."""


async def billing(admin, points="100", rules=None):
    response = await admin.api.put(
        "/api/v1/llm/point-conversion",
        json={"version": 0, "currency": "USD", "points_per_currency": "100"},
    )
    assert response.status_code == 200, response.text
    response = await admin.api.post(
        "/api/v1/quota/policies",
        json={
            "name": "Test quota",
            "is_default": True,
            "rules": rules or [{"kind": "fixed_hours", "hours": 5, "points": points}],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()

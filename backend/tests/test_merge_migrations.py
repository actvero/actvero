"""Both shipped database histories upgrade without changing existing resources."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.llm.models import CatalogModel
from app.modules.skills.models import Skill, SkillCategoryRecord
from app.modules.tenants.models import Tenant


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start",
    [
        "base",
        "79j_skill_categories",
        "91l_model_import_receipts",
        "92m_merge_skills_gateway",
        "93n_model_binding_ids",
        "94o_channel_management",
        "95p_diagnostic_calls",
        "96q_route_protection",
        "97r_settlement_evidence",
        "93n_platform_operators",
        "98s_platform_mail",
        "100u_opening_flows",
        "93n_experts",
        "94o_channel_routing",
        "95p_merge_experts_routing",
        "111f_unified_branding",
        "112g_management_mcp_oauth",
    ],
)
async def test_both_migration_branches_upgrade_with_data_preserved(start):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    cfg = Config("alembic.ini")
    assert ScriptDirectory.from_config(cfg).get_heads() == ["113h_management_merge"]
    schema = "test_merge_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with owner.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:

            def upgrade(sync, target):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, target)

            await connection.run_sync(upgrade, start)
            preserved = {}
            if start != "base":
                tenant = uuid4()
                await connection.execute(
                    Tenant.__table__.insert().values(id=tenant, name="保留组织")
                )
                if start == "79j_skill_categories":
                    await connection.execute(
                        SkillCategoryRecord.__table__.insert().values(
                            tenant_id=tenant,
                            id="uncategorized",
                            name="未分类",
                            name_key="未分类",
                            position=0,
                        )
                    )
                    await connection.execute(
                        Skill.__table__.insert().values(
                            tenant_id=tenant,
                            name="preserved-skill",
                            display_name="保留技能",
                            description="original",
                            audience="selected",
                            member_ids=[],
                        )
                    )
                    tables = ["tenants", "skills", "skill_categories"]
                else:
                    await connection.execute(
                        CatalogModel.__table__.insert().values(
                            tenant_id=tenant,
                            slug="preserved-model",
                            name="保留模型",
                            configuration={
                                "operations": [],
                                "audience": "selected",
                                "marker": "keep",
                            },
                        )
                    )
                    tables = ["tenants", "llm_models"]
                for table in tables:
                    preserved[table] = list(
                        (
                            await connection.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))
                        ).scalars()
                    )
            await connection.run_sync(upgrade, "head")
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalars().all() == ["113h_management_merge"]
            for table, rows in preserved.items():
                assert (
                    list(
                        (
                            await connection.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))
                        ).scalars()
                    )
                    == rows
                )
            for table in [
                "skills",
                "skill_categories",
                "llm_models",
                "access_keys",
                "llm_model_import_receipts",
                "llm_mutation_receipts",
                "experts",
                "expert_releases",
                "expert_categories",
                "platform_operators",
                "organization_opening_flows",
            ]:
                assert await connection.scalar(
                    text("SELECT to_regclass(:name)"), {"name": f"{schema}.{table}"}
                )
    finally:
        await engine.dispose()
        async with owner.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()

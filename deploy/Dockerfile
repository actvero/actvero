# Build both application and identity theme from the same source snapshot.
FROM --platform=$BUILDPLATFORM node:24-bookworm-slim@sha256:2fe369e969550cde8e867afc3fe370b260140cab4a23d467074295b42163d553 AS node
FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS python-base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# The web bundle and identity CSS are architecture independent. Build them on
# the operator host rather than emulating Node when packaging server images.
FROM --platform=$BUILDPLATFORM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS web-build
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install --global pnpm@11.25.0
WORKDIR /build/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile --store-dir /pnpm/store --fetch-timeout 180000
COPY frontend/ ./
COPY scripts/build-identity-theme.py /build/scripts/build-identity-theme.py
COPY identity/ /build/identity/
# Frontend type checks share the canonical Skills icon catalog.
COPY backend/app/modules/skills/assets/icons.json /build/backend/app/modules/skills/assets/icons.json
RUN pnpm build

FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv

FROM python-base AS api-build
COPY --from=uv /uv /uvx /bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project

FROM quay.io/keycloak/keycloak:26.7.4@sha256:82a77884f3af238beab1e7afd63b5f530e1b5c0590bd7aa60b40a40463e29b2c AS identity
COPY --from=web-build --chown=keycloak:keycloak /build/identity/themes/actvero /opt/keycloak/themes/actvero
COPY --chown=keycloak:keycloak identity/bootstrap/actvero-realm.json /opt/keycloak/data/import/actvero-realm.json

FROM python-base AS app
RUN groupadd --gid 10001 actvero && useradd --uid 10001 --gid actvero --create-home actvero
RUN mkdir -p /app/data/llm-outbox && chown -R actvero:actvero /app/data
WORKDIR /app/backend
COPY --from=api-build /app/backend/.venv /app/backend/.venv
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY --from=web-build /build/frontend/dist /app/frontend/dist
COPY LICENSE THIRD_PARTY_NOTICES.md /app/licenses/
COPY frontend/LICENSE /app/licenses/frontend-LICENSE
COPY frontend/public/notices/ /app/licenses/notices/
COPY frontend/src/assets/provider-avatars/LICENSE /app/licenses/provider-avatars-LICENSE
ENV PATH="/app/backend/.venv/bin:$PATH"
USER actvero
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]

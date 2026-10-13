#!/bin/sh
# Generate credentials using Docker; host Python/Node/pnpm/uv are not required.
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
environment_file=${1:-"$project_root/.env"}
environment_directory=$(CDPATH= cd -- "$(dirname -- "$environment_file")" && pwd)
environment_name=$(basename -- "$environment_file")
if [ -e "$environment_directory/$environment_name" ]; then
  printf '%s\n' '.env 已存在，保留原配置。'
  exit 0
fi
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$project_root,target=/workspace,readonly" \
  --mount "type=bind,source=$environment_directory,target=/config" \
  --workdir /workspace \
  python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e \
  python scripts/env.py --output "/config/$environment_name"

# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# ---------------------------------------------------------------------------
# Standalone Eigent Brain (FastAPI/uvicorn) image.
#
# This replaces the old `eigent/server` Dockerfile. The brain is the
# single-user, on-device backend that eigent-theia's agent panel talks to.
# It does NOT need Postgres, Redis or Celery (persistence is local files
# under $HOME/.eigent, plus local vector stores). See docker-compose.yml for
# how it is published on the host's port 3001.
#
# Build from the repo root (context must include the `brain/` tree):
#   docker compose up -d --build api
# ---------------------------------------------------------------------------
# Use a Python image with uv pre-installed. The brain pins requires-python
# ">=3.11,<3.12", so use the 3.11 bookworm-slim image.
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Install the project into `/app`
WORKDIR /app

# Install Git and build dependencies (required for git-based dependencies and
# Rust packages like tiktoken / camel-rs native wheels).
RUN apt-get update -o Acquire::Retries=3 && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    gcc \
    python3-dev \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

# Add Rust to PATH
ENV PATH="/root/.cargo/bin:$PATH"

# Disable bytecode transfer during compilation to avoid EMFILE during build on
# low nofile limits
ENV UV_COMPILE_BYTECODE=0

# Set UV HTTP Timeout to 300 seconds for slower networks
ENV UV_HTTP_TIMEOUT=300

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Install netcat for optional connectivity checks (kept for parity with the
# old image; the brain itself does not require it).
RUN apt-get update -o Acquire::Retries=3 && apt-get install -y --no-install-recommends \
    curl netcat-openbsd && rm -rf /var/lib/apt/lists/*

# The brain writes persistence + camel logs under $HOME/.eigent — keep home
# writable (already /root by default) and surface it for logging/volumes.
ENV HOME=/root

# Copy dependency files first for layer caching.
COPY brain/pyproject.toml brain/uv.lock ./

# Install the project's dependencies.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project --no-dev

# Then add the rest of the project source code and install it.
# Installing separately from its dependencies allows optimal layer caching.
COPY brain/ /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# Compile localization catalogs (babel).
RUN uv run pybabel compile -d lang 2>/dev/null || true

# Bake the latest brain/ commit into the image for stale-server detection.
# Uses --mount=type=bind to access .git without adding it to a layer.
RUN --mount=type=bind,source=.git,target=/tmp/.git \
    echo "EIGENT_BRAIN_GIT_COMMIT=$(git --git-dir=/tmp/.git log -1 --format=%H -- brain/ 2>/dev/null || echo unknown)" > /app/.image_env

# Place executables in the environment at the front of the path.
ENV PATH="/app/.venv/bin:$PATH"

# The FastAPI app is exported as `main:api` (see brain/main.py) and launched via
# `python main.py`, which starts uvicorn internally on EIGENT_BRAIN_PORT (default
# 5001). We bind 0.0.0.0 so Docker can publish it.
ENV EIGENT_BRAIN_HOST=0.0.0.0
EXPOSE 5678

# Reset the entrypoint — don't invoke `uv`.
ENTRYPOINT []

CMD ["python", "main.py"]

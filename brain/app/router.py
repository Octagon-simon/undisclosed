# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Portions Copyright 2026 Simon Ugorji. All Rights Reserved.
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
"""
Centralized router registration for the Eigent API.
All routers are explicitly registered here
for better visibility and maintainability.
"""

import logging

from fastapi import Depends, FastAPI

from app.auth import get_brain_auth_context
from app.controller import (
    browser_stream_controller,
    chat_controller,
    file_controller,
    git_controller,
    health_controller,
    mcp_controller,
    memory_controller,
    message_controller,
    model_controller,
    remote_sub_agent_controller,
    skill_controller,
    task_controller,
    tool_controller,
    workspace_controller,
)

logger = logging.getLogger("router")


def register_routers(app: FastAPI, prefix: str = "") -> None:
    """
    Register all API routers with their respective prefixes and tags.

    This replaces the auto-discovery mechanism for better:
    - Visibility: See all routes in one place
    - Maintainability: Easy to add/remove routes
    - Debugging: Clear registration order and configuration

    Args:
        app: FastAPI application instance
        prefix: Optional global prefix for all routes (e.g., "/api")
    """
    routers_config = [
        {
            "router": health_controller.router,
            "tags": ["Health"],
            "description": "Health check endpoint for service readiness",
        },
        {
            "router": file_controller.router,
            "tags": ["Files"],
            "description": "File upload for Web/Channel clients",
        },
        {
            "router": mcp_controller.router,
            "tags": ["MCP"],
            "description": "MCP config (list, install, remove, update)",
        },
        {
            "router": memory_controller.router,
            "tags": ["Memory"],
            "description": "Semantic memory status + clear",
        },
        {
            "router": skill_controller.router,
            "tags": ["Skills"],
            "description": "Skills scan, write, read, delete",
        },
        {
            "router": chat_controller.router,
            "tags": ["chat"],
            "description": "Chat session management, improvements, and human interactions",
        },
        {
            "router": message_controller.router,
            "tags": ["Message Router"],
            "description": "Phase 2 Message Router - /messages endpoint (prefix-aware)",
        },
        {
            "router": model_controller.router,
            "tags": ["model"],
            "description": "Model validation and configuration",
        },
        {
            "router": remote_sub_agent_controller.router,
            "tags": ["remote-sub-agent"],
            "description": "Remote sub-agent validation",
        },
        {
            "router": task_controller.router,
            "tags": ["task"],
            "description": "Task lifecycle management (start, stop, update, control)",
        },
        {
            "router": tool_controller.router,
            "tags": ["tool"],
            "description": "Tool installation and management",
        },
        {
            "router": workspace_controller.router,
            "tags": ["workspace"],
            "description": "Space-level local workspace binding",
        },
    ]

    app.include_router(health_controller.router, tags=["Health"])
    logger.info(
        "Registered Health router at root level for Docker health checks"
    )

    # Root-level, no brain-auth dependency: this is a WebSocket (the browser WS
    # API can't send an Authorization header) and the Brain binds to localhost.
    app.include_router(browser_stream_controller.router, tags=["BrowserStream"])
    logger.info("Registered BrowserStream WebSocket router at root level")

    # Root-level, no brain-auth: called by the Theia Source Control button.
    app.include_router(git_controller.router, tags=["Git"])
    logger.info("Registered Git (AI commit message) router at root level")

    for config in routers_config:
        dependencies = (
            []
            if config["tags"] == ["Health"]
            else [Depends(get_brain_auth_context)]
        )
        app.include_router(
            config["router"],
            prefix=prefix,
            tags=config["tags"],
            dependencies=dependencies,
        )
        route_count = len(config["router"].routes)
        logger.info(
            f"Registered {config['tags'][0]} router:"
            f" {route_count} routes -"
            f" {config['description']}"
        )

    # Register chat history router under /api/v1 (assistant message persistence)
    try:
        from app.controller import chat_history_controller

        app.include_router(
            chat_history_controller.router,
            prefix=prefix + "/api/v1",
            tags=["chat-history"],
            dependencies=[Depends(get_brain_auth_context)],
        )
        logger.info("Registered chat-history router under /api/v1")
    except Exception:
        logger.warning(
            "Failed to register chat-history router; assistant message persistence API unavailable",
            exc_info=True,
        )

    # Register local chat-platform router under /api/v1 (user + history API) —
    # this is the REST surface that makes eigent-theia standalone (no external
    # eigent/server Docker backend): auto-login, chat/histories, chat/history.
    try:
        from app.controller import chat_platform_controller

        app.include_router(
            chat_platform_controller.router,
            prefix=prefix + "/api/v1",
            tags=["chat-platform"],
            dependencies=[Depends(get_brain_auth_context)],
        )
        logger.info("Registered chat-platform router under /api/v1")
    except Exception:
        logger.warning(
            "Failed to register chat-platform router; local user/history API unavailable",
            exc_info=True,
        )

    # Register local Spaces/Projects router under /api/v1 — the REST surface the
    # History panel + sidebar use to list spaces and their conversations. Without
    # it every `/api/v1/spaces*` call 404s and the panel shows "No conversations".
    try:
        from app.controller import space_controller

        app.include_router(
            space_controller.router,
            prefix=prefix + "/api/v1",
            tags=["spaces"],
            dependencies=[Depends(get_brain_auth_context)],
        )
        logger.info("Registered spaces router under /api/v1")
    except Exception:
        logger.warning(
            "Failed to register spaces router; local Spaces/Projects API unavailable",
            exc_info=True,
        )

    logger.info(f"Total routers registered: {len(routers_config)}")

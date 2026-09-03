# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
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
# ========= Copyright 2026 Simon Ugorji. All Rights Reserved. =========
"""
Anthropic identity-linked API keys require an `anthropic-workspace-id` header on
EVERY request. Setting it as `default_headers` on the chat client covers the
`/v1/messages` call, but camel builds a SEPARATE `AnthropicTokenCounter` whose
client has NO default headers — so its pre-flight `/v1/messages/count_tokens`
call fails with a 400 before the chat call is even made.

This module builds a token counter whose client carries the workspace header, so
BOTH the count-tokens and messages calls authenticate correctly. Used by model
validation and by the runtime model factory.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("anthropic_workspace")

WORKSPACE_HEADER = "anthropic-workspace-id"


def extract_workspace_headers(
    default_headers: dict | None = None,
    model_config_dict: dict | None = None,
) -> dict[str, str]:
    """Return `{anthropic-workspace-id: <id>}` if present in either the client
    default_headers or model_config_dict.extra_headers (case-insensitive)."""
    headers: dict[str, str] = {}
    sources = [default_headers, (model_config_dict or {}).get("extra_headers")]
    for src in sources:
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(k, str) and k.lower() == WORKSPACE_HEADER and v:
                    headers[WORKSPACE_HEADER] = str(v).strip()
    return headers


def build_anthropic_token_counter(
    model_type: Any,
    api_key: str | None,
    url: str | None,
    headers: dict[str, str],
):
    """AnthropicTokenCounter whose underlying client carries `headers`. Returns
    None on any failure (caller then falls back to camel's default counter)."""
    try:
        from anthropic import Anthropic
        from camel.utils import AnthropicTokenCounter

        counter = AnthropicTokenCounter(
            str(model_type), api_key=api_key, base_url=url or None
        )
        # Replace the header-less client camel created with one that sends the
        # workspace id on the count_tokens call too.
        counter.client = Anthropic(
            api_key=api_key, base_url=url or None, default_headers=dict(headers)
        )
        return counter
    except Exception:
        logger.warning(
            "Failed to build header-carrying Anthropic token counter",
            exc_info=True,
        )
        return None


def maybe_inject_token_counter(
    model_platform: Any,
    model_type: Any,
    api_key: str | None,
    url: str | None,
    kwargs: dict,
    model_config_dict: dict | None,
) -> None:
    """If this is an Anthropic model AND a workspace header is present but no
    token_counter was supplied, inject a header-carrying counter into `kwargs`
    (mutated in place). No-op otherwise."""
    if str(model_platform).lower() != "anthropic":
        return
    if kwargs.get("token_counter") is not None:
        return
    headers = extract_workspace_headers(
        kwargs.get("default_headers"), model_config_dict
    )
    if not headers:
        return
    counter = build_anthropic_token_counter(model_type, api_key, url, headers)
    if counter is not None:
        kwargs["token_counter"] = counter

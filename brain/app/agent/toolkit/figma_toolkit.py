# Copyright (c) 2026 Simon Ugorji

"""Figma REST API toolkit.

Reads a Figma file's components/nodes programmatically, bypassing the browser
entirely — Figma renders on a single WebGL <canvas>, so its nodes are NOT
clickable DOM elements and the browser tools can't select them. The REST API
returns each node's real properties (fills, text style, geometry), which is
exactly what's needed for Figma -> code/Storybook work.

Enabled only when a FIGMA_ACCESS_TOKEN (a Figma personal access token) is set.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
from camel.toolkits import BaseToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env

logger = logging.getLogger("figma_toolkit")

_FILE_KEY_RE = re.compile(r"figma\.com/(?:file|design)/([A-Za-z0-9]+)")
_NODE_ID_RE = re.compile(r"[?&]node-id=([0-9A-Za-z:%-]+)")


def _int_env(key: str, default: int) -> int:
    try:
        return int(float(env(key, str(default))))
    except (TypeError, ValueError):
        return default


def _retry_after_seconds(resp: httpx.Response, fallback: float) -> float:
    """Seconds to wait before retrying a 429, honoring the `Retry-After`
    header when present (delta-seconds form), else the caller's backoff."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return max(0.0, float(header.strip()))
        except (TypeError, ValueError):
            pass  # HTTP-date form is rare here; fall back to backoff.
    return fallback


def _get_with_retry(
    url: str, headers: dict[str, str], timeout: float
) -> httpx.Response:
    """GET that transparently retries HTTP 429 (Figma rate limit) with capped
    exponential backoff, so the agent no longer has to `sleep` between calls.

    Bounds keep a rate-limited call from blocking the tool thread for long:
    up to FIGMA_MAX_RETRIES attempts (default 3), each wait capped at
    FIGMA_MAX_BACKOFF seconds (default 20). On the final 429 the response is
    returned so the caller can surface a clear "try again shortly" message.
    """
    max_retries = max(0, _int_env("FIGMA_MAX_RETRIES", 3))
    max_backoff = max(1, _int_env("FIGMA_MAX_BACKOFF", 20))
    resp = httpx.get(url, headers=headers, timeout=timeout)
    attempt = 0
    while resp.status_code == 429 and attempt < max_retries:
        backoff = min(max_backoff, 2 ** (attempt + 1))  # 2, 4, 8, … capped
        wait = min(max_backoff, _retry_after_seconds(resp, backoff))
        logger.info(
            "Figma 429 (attempt %d/%d); backing off %.1fs",
            attempt + 1,
            max_retries,
            wait,
        )
        time.sleep(wait)
        attempt += 1
        resp = httpx.get(url, headers=headers, timeout=timeout)
    return resp


def _rgba_to_hex(color: dict[str, Any]) -> str:
    def c(v: float) -> int:
        return max(0, min(255, round(float(v) * 255)))

    r, g, b = c(color.get("r", 0)), c(color.get("g", 0)), c(color.get("b", 0))
    a = color.get("a", 1)
    hexv = f"#{r:02X}{g:02X}{b:02X}"
    return hexv if a in (1, None) else f"{hexv} (alpha {round(float(a), 2)})"


def _fills_summary(fills: list[dict] | None) -> str:
    out = []
    for f in fills or []:
        if f.get("visible") is False:
            continue
        if f.get("type") == "SOLID" and f.get("color"):
            op = f.get("opacity")
            hexv = _rgba_to_hex(f["color"])
            out.append(hexv + (f" @ {round(op,2)}" if op not in (None, 1) else ""))
        elif f.get("type"):
            out.append(f["type"].lower())
    return ", ".join(out)


def _node_summary(node: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"- name: {node.get('name')}  (type: {node.get('type')})")
    if node.get("characters"):
        text = str(node["characters"]).replace("\n", " ")[:80]
        lines.append(f"  text: {text!r}")
    style = node.get("style") or {}
    if style:
        parts = []
        for k, label in (
            ("fontFamily", "font"),
            ("fontWeight", "weight"),
            ("fontSize", "size"),
            ("lineHeightPx", "line-height"),
            ("letterSpacing", "letter-spacing"),
            ("textAlignHorizontal", "align"),
            ("textAlignVertical", "valign"),
        ):
            if style.get(k) not in (None, ""):
                parts.append(f"{label}={style[k]}")
        if parts:
            lines.append("  typography: " + ", ".join(parts))
    fills = _fills_summary(node.get("fills"))
    if fills:
        lines.append(f"  fill: {fills}")
    strokes = _fills_summary(node.get("strokes"))
    if strokes:
        sw = node.get("strokeWeight")
        lines.append(f"  border: {strokes}" + (f" ({sw}px)" if sw else ""))
    if node.get("cornerRadius") is not None:
        lines.append(f"  radius: {node['cornerRadius']}px")
    pads = {
        k: node[k]
        for k in ("paddingLeft", "paddingRight", "paddingTop", "paddingBottom")
        if node.get(k) is not None
    }
    if pads:
        lines.append("  padding: " + ", ".join(f"{k[7:].lower()}={v}" for k, v in pads.items()))
    box = node.get("absoluteBoundingBox") or {}
    if box.get("width") is not None:
        lines.append(f"  size: {round(box['width'])}x{round(box['height'])}")
    if node.get("opacity") not in (None, 1):
        lines.append(f"  opacity: {round(float(node['opacity']), 2)}")
    return "\n".join(lines)


class FigmaToolkit(BaseToolkit, AbstractToolkit):
    """Read Figma nodes/components via the REST API."""

    def __init__(
        self,
        api_task_id: str,
        agent_name: str | None = None,
        timeout: float | None = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.api_task_id = api_task_id
        if agent_name is not None:
            self.agent_name = agent_name

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        if env("FIGMA_ACCESS_TOKEN"):
            return cls(api_task_id).get_tools()
        return []

    def _parse_url(self, figma_url: str) -> tuple[str | None, str | None]:
        key_m = _FILE_KEY_RE.search(figma_url or "")
        node_m = _NODE_ID_RE.search(figma_url or "")
        file_key = key_m.group(1) if key_m else None
        node_id = None
        if node_m:
            # URL uses `9356-65502`; the API expects `9356:65502`.
            node_id = node_m.group(1).replace("%3A", ":").replace("-", ":")
        return file_key, node_id

    def figma_read(self, figma_url: str) -> str:
        """Read a Figma node's real design properties (colors, text style,
        geometry) via the Figma API — use this instead of the browser for
        Figma, whose canvas nodes are not clickable DOM elements.

        Args:
            figma_url: A Figma file/frame URL, ideally with a `node-id`
                (e.g. https://www.figma.com/design/<key>/...?node-id=9356-65502).

        Returns:
            A compact, readable summary of the selected node and its children
            (name, type, fill/border colors as hex, typography, radius, padding,
            size), or an error note.
        """
        token = env("FIGMA_ACCESS_TOKEN")
        if not token:
            return "FIGMA_ACCESS_TOKEN is not set; cannot read Figma."
        file_key, node_id = self._parse_url(figma_url)
        if not file_key:
            return (
                "Could not find a Figma file key in that URL. Paste the full "
                "figma.com/design/<key>/... link."
            )
        headers = {"X-Figma-Token": token}
        try:
            if node_id:
                url = f"https://api.figma.com/v1/files/{file_key}/nodes?ids={node_id}"
            else:
                url = f"https://api.figma.com/v1/files/{file_key}?depth=2"
            resp = _get_with_retry(url, headers, self.timeout or 30.0)
            if resp.status_code == 403:
                return "Figma API returned 403 — the token can't access this file."
            if resp.status_code == 429:
                # Still rate-limited after ret/backoff. Tell the agent to move on
                # to other work and come back — do NOT instruct it to sleep.
                return (
                    "Figma API is rate-limiting requests (HTTP 429) and is still "
                    "limited after automatic retries. Do NOT wait or sleep for "
                    "it — continue with other work (e.g. reading the local code) "
                    "and read this node again in a minute."
                )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            return f"Figma API request failed: {exc}"

        # Collect the target node + its immediate descendants (bounded).
        roots: list[dict] = []
        if node_id:
            for entry in (data.get("nodes") or {}).values():
                doc = entry.get("document")
                if doc:
                    roots.append(doc)
        else:
            doc = data.get("document")
            if doc:
                roots.append(doc)
        if not roots:
            return "No matching node found for that URL."

        summaries: list[str] = []
        count = 0

        def walk(node: dict, depth: int) -> None:
            nonlocal count
            if count >= 60:
                return
            summaries.append(_node_summary(node))
            count += 1
            if depth <= 0:
                return
            for child in node.get("children") or []:
                walk(child, depth - 1)

        for root in roots:
            walk(root, 2)
        header = f"Figma file {file_key}" + (f", node {node_id}" if node_id else "")
        return header + ":\n" + "\n".join(summaries)

    def get_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.figma_read)]

    @classmethod
    def toolkit_name(cls) -> str:
        return "Figma Toolkit"

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

import asyncio
import glob
import json
import logging
import os
import shutil
import time

from fastapi import APIRouter, HTTPException

from app.service.mcp_config import (
    add_mcp,
    read_mcp_config,
    remove_mcp,
    update_mcp,
)

router = APIRouter()
mcp_logger = logging.getLogger("mcp_controller")


@router.get("/mcp/list")
def mcp_list() -> dict:
    """List all MCP servers (global config)."""
    return read_mcp_config()


@router.post("/mcp/install")
def mcp_install(body: dict) -> dict:
    """Install/add MCP server to global config. Body: { name, mcp }."""
    name = body.get("name")
    mcp = body.get("mcp")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not mcp or not isinstance(mcp, dict):
        raise HTTPException(status_code=400, detail="mcp object is required")
    add_mcp(str(name).strip(), mcp)
    mcp_logger.info("MCP installed: %s", name)
    return {"success": True}


@router.delete("/mcp/{name}")
def mcp_remove(name: str) -> dict:
    """Remove MCP server from global config."""
    remove_mcp(name)
    mcp_logger.info("MCP removed: %s", name)
    return {"success": True}


@router.put("/mcp/{name}")
def mcp_update(name: str, mcp: dict) -> dict:
    """Update MCP server in global config. Body is the mcp config object."""
    update_mcp(name, mcp)
    mcp_logger.info("MCP updated: %s", name)
    return {"success": True}


def _mcp_remote_url(server: dict) -> str | None:
    """Return the remote URL an `mcp-remote` command server wraps, else None."""
    if not isinstance(server, dict) or not server.get("command"):
        return None
    args = server.get("args") or []
    if not any("mcp-remote" in str(a) for a in args):
        return None
    for a in args:
        s = str(a)
        if s.startswith("http://") or s.startswith("https://"):
            return s
    return None


async def _run_oauth_login(
    command: str, args: list[str], timeout: float = 180.0
) -> dict:
    """Run the connector's EXACT `mcp-remote` command interactively.

    We run the server's configured command + args (so any pinned callback port
    and `--static-oauth-client-info` for pre-registered clients are honored — not
    just the bare URL). mcp-remote opens the user's browser, runs a local
    callback server, and on a successful sign-in caches the token under
    MCP_REMOTE_CONFIG_DIR (~/.mcp-auth). We watch that directory for a new token
    file, then stop the process. Run OUTSIDE the agent's (timeout-bounded,
    headless) task connection so the human has time to authorize.
    """
    exe = shutil.which(command) or command
    if command == "npx" and not shutil.which("npx"):
        return {
            "success": False,
            "message": "npx (Node.js) not found — cannot run the OAuth bridge.",
        }
    auth_dir = os.environ.get(
        "MCP_REMOTE_CONFIG_DIR", os.path.expanduser("~/.mcp-auth")
    )
    os.makedirs(auth_dir, exist_ok=True)

    # The token filename is deterministic (a hash of the server URL), so a
    # re-auth UPDATES the same file rather than creating a new one. Detect a
    # FRESH token by mtime instead of "a new path appeared" (which missed it).
    start = time.time()

    def _fresh_token() -> bool:
        for p in glob.glob(
            os.path.join(auth_dir, "**", "*_tokens.json"), recursive=True
        ):
            try:
                if os.path.getmtime(p) >= start - 2:
                    return True
            except OSError:
                pass
        return False

    env = dict(os.environ)
    env["MCP_REMOTE_CONFIG_DIR"] = auth_dir
    # Capture output so we can surface the REAL failure reason to the user
    # (e.g. "does not support dynamic client registration") instead of a generic
    # message.
    proc = await asyncio.create_subprocess_exec(
        exe,
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    # On SUCCESS mcp-remote connects and KEEPS RUNNING (it doesn't exit), so we
    # detect success from its output stream — not a process exit or a new token
    # file (a re-auth reuses the cached token and rewrites nothing).
    success_markers = (
        "proxy established",
        "connected to remote server",
        "local stdio server running",
    )
    dyn_reg_msg = (
        "This server requires a PRE-REGISTERED OAuth app (it doesn't support "
        "automatic registration). Easiest fix: use a Personal Access Token "
        "instead — add the server as Streamable HTTP with the token as the auth "
        "token. Otherwise register an OAuth app in the provider's developer "
        "console."
    )
    tail: list[str] = []
    try:
        while True:
            if time.time() - start > timeout:
                return {
                    "success": False,
                    "message": "Timed out waiting for sign-in. Complete the "
                    "browser authorization, then try again.",
                }
            if _fresh_token():
                return {
                    "success": True,
                    "message": "Authenticated — token cached.",
                }
            try:
                raw = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=2.0
                )
            except asyncio.TimeoutError:
                continue  # re-check token / timeout
            if not raw:  # EOF → the bridge exited
                break
            line = raw.decode(errors="replace").rstrip()
            tail.append(line)
            del tail[:-40]
            low = line.lower()
            if any(m in low for m in success_markers):
                return {"success": True, "message": "Authenticated — connected."}
            if "fatal error" in low or "connection error" in low:
                if "dynamic client registration" in low:
                    return {"success": False, "message": dyn_reg_msg}
                return {"success": False, "message": line}

        # process exited without a clear success/error marker
        if _fresh_token():
            return {"success": True, "message": "Authenticated — token cached."}
        err = next(
            (line for line in reversed(tail) if "error" in line.lower()), ""
        )
        if "dynamic client registration" in err.lower():
            return {"success": False, "message": dyn_reg_msg}
        return {
            "success": False,
            "message": err
            or "Sign-in did not complete (the OAuth bridge exited).",
        }
    finally:
        try:
            proc.terminate()
        except Exception:
            pass


@router.post("/mcp/authenticate")
async def mcp_authenticate(body: dict) -> dict:
    """Kick off the interactive OAuth sign-in for an `mcp-remote` connector.

    Body: { name }. Opens the user's browser to authorize; returns once the
    token is cached (or on timeout). Only valid for OAuth (mcp-remote) servers.
    """
    name = (body or {}).get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    server = (read_mcp_config().get("mcpServers") or {}).get(str(name))
    if not server:
        raise HTTPException(status_code=404, detail="unknown connector")
    url = _mcp_remote_url(server)
    if not url:
        return {
            "success": False,
            "message": "This connector does not use OAuth (mcp-remote); no "
            "sign-in needed.",
        }
    command = str(server.get("command"))
    args = [str(a) for a in (server.get("args") or [])]
    mcp_logger.info("Starting OAuth sign-in for MCP: %s", name)
    result = await _run_oauth_login(command, args)
    if result.get("success"):
        _mark_authenticated(str(name))
    return result


_AUTHED_MARKER = os.path.expanduser("~/.eigent/mcp_authed.json")


def _read_authed() -> dict:
    try:
        with open(_AUTHED_MARKER) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mark_authenticated(name: str) -> None:
    try:
        data = _read_authed()
        data[name] = int(time.time())
        os.makedirs(os.path.dirname(_AUTHED_MARKER), exist_ok=True)
        with open(_AUTHED_MARKER, "w") as f:
            json.dump(data, f)
    except Exception:
        mcp_logger.debug("could not persist auth marker", exc_info=True)


@router.get("/mcp/auth-status")
def mcp_auth_status() -> dict:
    """Names of connectors that have completed OAuth sign-in (persisted), so the
    UI can show 'Authenticated' across reloads. Filtered to servers still present
    in the config."""
    known = set((read_mcp_config().get("mcpServers") or {}).keys())
    authed = [name for name in _read_authed() if name in known]
    return {"authenticated": authed}

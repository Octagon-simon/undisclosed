# Copyright (c) 2026 Simon Ugorji
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Web page camera backed by the bundled `iris` binary.

`iris` (github.com/brijr/iris, MIT) drives Chrome over CDP and writes a PNG.
One process per shot, no interaction, no shared browser session: this is the
"look at the rendered page" primitive the agent was missing. Calls are
async and concurrent, so one tool call can return desktop + mobile + dark in a
single model step.
"""

import asyncio
import base64
import json
import logging
import os
import platform
import re
import shutil
import sys
from pathlib import Path

from camel.toolkits import BaseToolkit, FunctionTool, RegisteredAgentToolkit
from camel.utils.tool_result import ToolResult

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.utils.listen.toolkit_listen import listen_toolkit
from app.utils.model_capabilities import model_supports_vision

logger = logging.getLogger("iris_toolkit")

_BIN_NAME = "iris.exe" if platform.system() == "Windows" else "iris"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_SHOTS = 4
_MAX_ATTACHED = 3

_chrome_path: str | None = None
_chrome_resolved = False


def _platform_dir() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _candidate_roots() -> list[Path]:
    """Where a bundled `iris` may live, in priority order."""
    roots: list[Path] = []
    if _is_frozen():
        # PyInstaller: <Resources>/brain/undisclosed-brain; iris sits at
        # <Resources>/binaries/iris/<os>-<arch>/iris.
        exe_dir = Path(sys.executable).resolve().parent
        roots.extend([exe_dir.parent, exe_dir])
    backend_root = Path(__file__).resolve().parent.parent.parent
    roots.extend([backend_root.parent, backend_root.parent.parent])
    return roots


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-") or "page"


def _url_slug(url: str) -> str:
    body = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", url)
    return _safe_name(body)[:80]


def _resolve_chrome() -> str | None:
    """Cached Chromium path, so iris uses the app's browser instead of
    depending on a system Chrome. None lets iris auto-detect."""
    global _chrome_path, _chrome_resolved
    if _chrome_resolved:
        return _chrome_path
    _chrome_resolved = True
    try:
        from app.utils.browser_launcher import _find_chrome_executable

        _chrome_path = _find_chrome_executable()
    except Exception:
        logger.debug("Chrome lookup failed; letting iris auto-detect")
    return _chrome_path


class IrisToolkit(BaseToolkit, RegisteredAgentToolkit, AbstractToolkit):
    agent_name: str

    @classmethod
    def toolkit_name(cls) -> str:
        # Deliberately descriptive: this is what load_capability advertises.
        return "Page Screenshots"

    @classmethod
    def resolve_binary(cls) -> str | None:
        override = os.environ.get("IRIS_BIN") or env("IRIS_BIN", "")
        if override:
            path = Path(override).expanduser()
            if path.is_file():
                return str(path)
            logger.warning("IRIS_BIN set but not a file: %s", path)

        candidates = [Path.home() / ".undisclosed" / "bin" / _BIN_NAME]
        rel = Path("binaries") / "iris" / _platform_dir() / _BIN_NAME
        for root in _candidate_roots():
            candidates.append(root / rel)
            candidates.append(root / "resources" / rel)
        for path in candidates:
            if path.is_file():
                return str(path)

        found = shutil.which("iris")
        return found

    def __init__(
        self,
        api_task_id: str,
        agent_name: str = "Single Agent",
        working_directory: str | None = None,
        timeout: float | None = 180,
        shot_dir: str | None = None,
        max_concurrency: int = 2,
        model_type: str | None = None,
        model_platform: str | None = None,
    ):
        BaseToolkit.__init__(self, timeout)
        RegisteredAgentToolkit.__init__(self)
        self.api_task_id = api_task_id
        self.agent_name = agent_name
        self.working_directory = working_directory or os.getcwd()
        self.shot_dir = shot_dir or env("IRIS_SHOT_DIR", "") or ""
        self.max_concurrency = max(1, int(max_concurrency))
        self.model_type = model_type
        self.model_platform = model_platform
        self._binary = self.resolve_binary()
        self._sem = asyncio.Semaphore(self.max_concurrency)

    # ------------------------------------------------------------------ tool

    def get_tools(self) -> list[FunctionTool]:
        return [FunctionTool(self.capture_page)]

    @listen_toolkit()
    async def capture_page(
        self,
        url: str,
        selector: str = "",
        padding: int = 24,
        size: str = "desktop",
        sizes: list[str] | None = None,
        dark: bool = False,
        full_page: bool = False,
        wait_for: str = "",
        wait_ms: int = 0,
        out: str = "",
        read_image: bool = True,
    ) -> str | ToolResult:
        r"""Capture a live web page to PNG, then see it.

        Use this to verify rendered UI: after building or editing a page, to
        check layout, spacing, theme, or responsive breakpoints. The shot is
        attached to your context when your model can see images, so one call
        is enough; pass read_image=False to only get file paths.

        Args:
            url (str): Page URL, e.g. "http://localhost:3000".
            selector (str): CSS selector to crop to a single element
                (e.g. "#pricing-card"). Mutually exclusive with full_page.
            padding (int): CSS pixels of padding around a selected element.
            size (str): Viewport preset "desktop", "iphone", "ipad", or
                "WxH" (e.g. "1280x720"). Default "desktop".
            sizes (list[str], optional): Capture several viewports in one
                call (e.g. ["desktop", "iphone"]). Overrides size.
            dark (bool): Emulate prefers-color-scheme: dark.
            full_page (bool): Capture the whole scrollable page.
            wait_for (str): Wait until this CSS selector exists before
                capturing (use for client-rendered content).
            wait_ms (int): Extra settle delay in ms after smart waiting.
            out (str): Output file or directory; relative paths resolve
                against the workspace. Defaults to the app's shot cache.
            read_image (bool): Attach the screenshot image(s) to your
                context. Default True.

        Returns:
            The saved path(s) plus viewport details, with images attached
            when the model supports vision.
        """
        if not self._binary:
            return (
                "Error: the page camera binary (iris) is not installed for "
                f"{_platform_dir()}. Fall back to browser_get_page_snapshot "
                "or read_image of an existing file."
            )

        url = (url or "").strip()
        if not url:
            return "Error: capture_page needs a url."
        if "://" not in url:
            url = f"http://{url}"

        requested = [s for s in (sizes or []) if s]
        if not requested:
            requested = [size or "desktop"]
        requested = list(dict.fromkeys(requested))[:_MAX_SHOTS]

        if full_page and selector:
            return "Error: full_page and selector are mutually exclusive."

        out_dir, exact_file = self._resolve_out(out, len(requested))

        jobs = []
        for viewport in requested:
            name = (
                f"{_url_slug(url)}-{_safe_name(viewport)}"
                + ("-dark" if dark else "")
                + ".png"
            )
            target = exact_file or out_dir / name
            jobs.append((viewport, target))

        results = await asyncio.gather(
            *(
                self._capture_one(
                    url=url,
                    viewport=viewport,
                    target=target,
                    selector=selector,
                    padding=padding,
                    dark=dark,
                    full_page=full_page,
                    wait_for=wait_for,
                    wait_ms=wait_ms,
                )
                for viewport, target in jobs
            )
        )

        ok = [r for r in results if r["ok"]]
        errors = [r for r in results if not r["ok"]]
        if not ok:
            detail = "; ".join(f"{r['viewport']}: {r['error']}" for r in errors)
            return f"Error: page capture failed for {url} ({detail})"

        lines = [f"Captured {len(ok)} shot(s) of {url}:"]
        for r in ok:
            dims = (
                f"{r['width']}x{r['height']} @{r['scale']:g}x"
                if r.get("width")
                else "saved"
            )
            lines.append(f"- {r['path']} ({r['viewport']}, {dims})")
        if errors:
            lines.append(
                "Failed: "
                + "; ".join(f"{r['viewport']}: {r['error']}" for r in errors)
            )

        images = self._load_images(ok) if read_image else []
        lines.append(
            "Images attached to context."
            if images
            else "Open a path with read_image to view it."
        )
        text = "\n".join(lines)
        return ToolResult(text=text, images=images) if images else text

    # -------------------------------------------------------------- internals

    def _resolve_out(self, out: str, count: int) -> tuple[Path, Path | None]:
        if out:
            path = Path(out).expanduser()
            if not path.is_absolute():
                path = Path(self.working_directory) / path
            if count == 1 and path.suffix.lower() in _IMAGE_SUFFIXES:
                path.parent.mkdir(parents=True, exist_ok=True)
                return path.parent, path
            path.mkdir(parents=True, exist_ok=True)
            return path, None

        if self.shot_dir:
            root = Path(self.shot_dir).expanduser()
        else:
            root = (
                Path.home()
                / ".undisclosed"
                / "screenshots"
                / _safe_name(str(self.api_task_id or "default"))
            )
        root.mkdir(parents=True, exist_ok=True)
        return root, None

    async def _capture_one(
        self,
        *,
        url: str,
        viewport: str,
        target: Path,
        selector: str,
        padding: int,
        dark: bool,
        full_page: bool,
        wait_for: str,
        wait_ms: int,
    ) -> dict:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            try:
                target.unlink()
            except OSError:
                pass

        args = [
            self._binary,
            "--json",
            "--size",
            viewport,
            "--out",
            str(target),
            "--timeout",
            "45",
        ]
        if selector:
            args += ["--selector", selector, "--padding", str(max(0, padding))]
        elif full_page:
            args.append("--full")
        if dark:
            args.append("--dark")
        if wait_for:
            args += ["--wait-for", wait_for]
        if wait_ms > 0:
            args += ["--wait", str(int(wait_ms))]

        chrome = await asyncio.to_thread(_resolve_chrome)
        if chrome:
            args += ["--chrome", chrome]
        args.append(url)

        async with self._sem:
            report, error = await self._run(args)

        result = {"ok": False, "viewport": viewport, "path": str(target)}
        if error:
            result["error"] = error
            return result
        if not target.is_file() or target.stat().st_size == 0:
            result["error"] = report or "no file written"
            return result

        result.update(ok=True)
        if report:
            for key in ("css_width", "css_height", "scale"):
                if report.get(key) is not None:
                    result[key.replace("css_", "")] = report[key]
        return result

    async def _run(self, args: list[str]) -> tuple[dict | None, str | None]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            return None, f"cannot run iris: {exc}"

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=float(self.timeout or 120)
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None, "timed out"

        out = (stdout or b"").decode("utf-8", "replace").strip()
        err = (stderr or b"").decode("utf-8", "replace").strip()

        report: dict | None = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if parsed.get("status") == "ok":
                report = parsed
                break
            return None, str(parsed.get("error") or line)[:400]

        if proc.returncode != 0 and report is None:
            return None, (err or out or f"exit {proc.returncode}")[-400:]
        return report, None

    def _load_images(self, shots: list[dict]) -> list[str]:
        if not self._agent_sees_images():
            return []
        images: list[str] = []
        for shot in shots[:_MAX_ATTACHED]:
            try:
                data = Path(shot["path"]).read_bytes()
            except OSError:
                continue
            if not data:
                continue
            suffix = Path(shot["path"]).suffix.lower().lstrip(".") or "png"
            mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
            images.append(
                f"data:image/{mime};base64," + base64.b64encode(data).decode()
            )
        return images

    def _agent_sees_images(self) -> bool:
        if self.model_type or self.model_platform:
            return model_supports_vision(self.model_platform, self.model_type)
        try:
            # Only reached when the constructor got no model identity. Unwrap
            # ModelType so enum and string backends match the same markers.
            backend = self.agent.model_backend if self.agent else None
            model_type = getattr(backend, "model_type", None)
            value = getattr(model_type, "value", model_type)
            return model_supports_vision(None, str(value) if value else None)
        except Exception:
            return False

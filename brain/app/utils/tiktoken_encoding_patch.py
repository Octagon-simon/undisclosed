# Copyright (c) 2026 Simon Ugorji

"""Startup patch: make tiktoken resolve its encodings without entry-point plugins.

tiktoken discovers encodings (o200k_base, cl100k_base, …) through `tiktoken_ext`
packages registered as importlib entry points. In a frozen PyInstaller binary
(the packaged app's brain) those entry points are NOT discoverable, so tiktoken
raises `Unknown encoding o200k_base. Plugins found: []` — which breaks CAMEL's
token counter and, e.g., commit-message generation.

We force-register the constructors from `tiktoken_ext.openai_public` directly
into tiktoken's registry, bypassing entry-point discovery entirely. Idempotent
and best-effort: any failure leaves tiktoken untouched.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("tiktoken_encoding_patch")


def apply() -> None:
    try:
        import tiktoken.registry as registry
        import tiktoken_ext.openai_public as openai_public
    except Exception:  # pragma: no cover - tiktoken layout changed / not present
        logger.debug("tiktoken or tiktoken_ext not importable; patch skipped")
        return

    try:
        constructors = getattr(openai_public, "ENCODING_CONSTRUCTORS", None)
        if not constructors:
            logger.debug("no ENCODING_CONSTRUCTORS in tiktoken_ext.openai_public")
            return

        # tiktoken lazily builds registry.ENCODING_CONSTRUCTORS from entry points
        # under a lock. Seed it directly so `get_encoding` never needs the plugin
        # discovery that fails in the frozen binary.
        lock = getattr(registry, "_lock", None)
        if lock is not None:
            lock.acquire()
        try:
            if getattr(registry, "ENCODING_CONSTRUCTORS", None) is None:
                registry.ENCODING_CONSTRUCTORS = {}
            added = 0
            for name, ctor in constructors.items():
                if name not in registry.ENCODING_CONSTRUCTORS:
                    registry.ENCODING_CONSTRUCTORS[name] = ctor
                    added += 1
        finally:
            if lock is not None:
                lock.release()

        logger.info(
            "Force-registered %d tiktoken encodings (%s) — entry-point plugin "
            "discovery bypassed",
            added,
            ", ".join(sorted(constructors.keys())),
        )
    except Exception:  # pragma: no cover - never break startup
        logger.debug("tiktoken encoding force-register failed", exc_info=True)

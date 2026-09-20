#!/usr/bin/env python
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

"""LIVE shadow run: a REAL model over a REAL conversation, same code path.

`verify_llm_extraction.py` stubs the model so it can run with no API key. This
script does the opposite: it points the model pass at a real provider from
`~/.undisclosed/providers.json` and runs the *real* end-of-run pipeline
(`app.memory.hybrid.engine.process_run_end`) over a real project's transcript.

To keep it non-destructive it works on a COPY of the project memory dir under a
temp root, and it drops the project's newest run so that the "latest turn" is a
*completed* turn (the app only calls this at run end, when the assistant reply is
already in the transcript).

Usage:
  cd brain && PYTHONPATH=. .venv/bin/python scripts/verify_llm_extraction_live.py \
      --user user_0 --space <space_id> --project <project_id>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("UNDISCLOSED_HYBRID_MEMORY", "true")
os.environ["UNDISCLOSED_HYBRID_LLM_EXTRACTION"] = "shadow"

from app.memory import LocalMemoryStore  # noqa: E402
from app.memory.hybrid import engine, llm_extract, vector  # noqa: E402
from app.memory.hybrid.storage import HybridStore  # noqa: E402
from app.memory.local_store import read_jsonl_file  # noqa: E402

PROVIDERS = Path.home() / ".undisclosed" / "providers.json"


def _pick_provider() -> dict:
    rows = json.loads(PROVIDERS.read_text())
    # Prefer the user's preferred provider, else the first with a key.
    for row in rows:
        if row.get("prefer") and row.get("api_key"):
            return row
    for row in rows:
        if row.get("api_key"):
            return row
    raise SystemExit("no provider with an api_key in providers.json")


def _build_real_completer(provider: dict):
    """A blocking (system, user) -> text callable backed by the real model."""
    from camel.agents import ChatAgent
    from camel.messages import BaseMessage
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType, ModelType

    platform_name = (
        (provider.get("encrypted_config") or {}).get("model_platform")
        or provider.get("provider_name")
    )
    model_name = provider.get("model_type")
    api_key = provider.get("api_key")

    platform = getattr(ModelPlatformType, str(platform_name).upper().replace("-", "_"))
    try:
        model_type = ModelType(model_name)
    except ValueError:
        model_type = model_name

    model = ModelFactory.create(
        model_platform=platform, model_type=model_type, api_key=api_key
    )
    calls: list[int] = []

    def _complete(system: str, user: str) -> str:
        calls.append(len(user))
        agent = ChatAgent(
            BaseMessage.make_assistant_message(
                role_name="MemoryExtractor", content=system
            ),
            model=model,
        )
        return llm_extract._response_text(agent.step(user)) or ""

    _complete.calls = calls  # type: ignore[attr-defined]
    return _complete


def _copy_project(root: Path, user: str, space: str, project: str) -> Path:
    src = (
        Path.home()
        / ".undisclosed"
        / "memory"
        / "users"
        / user
        / "spaces"
        / space
        / "projects"
        / project
    )
    if not src.exists():
        raise SystemExit(f"project not found: {src}")
    dst = root / "memory" / "users" / user / "spaces" / space / "projects" / project
    shutil.copytree(src, dst)
    return dst


def _drop_newest_run(conv: Path) -> str:
    """Truncate the copied transcript to its last COMPLETED run."""
    rows = [json.loads(line) for line in conv.read_text().splitlines() if line.strip()]
    runs: list[str] = []
    for row in rows:
        if row.get("run_id") not in runs:
            runs.append(row.get("run_id"))
    if len(runs) < 2:
        raise SystemExit("need at least two runs in the transcript")
    newest = runs[-1]
    kept = [row for row in rows if row.get("run_id") != newest]
    conv.write_text("".join(json.dumps(row) + "\n" for row in kept))
    return newest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--space", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--budget-tokens", type=int, default=None)
    args = ap.parse_args()

    provider = _pick_provider()
    print(f"model: {provider.get('provider_name')} / {provider.get('model_type')}")

    root = Path(tempfile.mkdtemp(prefix="hybrid-live-"))
    print(f"isolated store root: {root / 'memory'}")
    project_dir = _copy_project(root, args.user, args.space, args.project)
    dropped = _drop_newest_run(project_dir / "conversation.jsonl")
    print(f"dropped in-progress run {dropped}; latest turn is now a completed one")

    completer = _build_real_completer(provider)
    llm_extract._default_completer = lambda: completer

    store = LocalMemoryStore(root=root / "memory")
    hybrid = HybridStore(store)
    summary = engine.process_run_end(
        hybrid,
        user_key=args.user,
        space_id=args.space,
        project_id=args.project,
        conversation_id=args.project,
        budget_tokens=args.budget_tokens,
    )
    print("\nsummary:", json.dumps(summary, default=str))
    print("model calls:", len(getattr(completer, "calls", [])))

    log_path = project_dir / "extraction_log.jsonl"
    rows = read_jsonl_file(log_path) if log_path.exists() else []
    print(f"\nextraction_log.jsonl rows: {len(rows)}")
    for row in rows:
        llm = row.get("llm")
        print(
            f"  mode={row['mode']} phase={row['phase']} "
            f"turns={row['start_turn']}-{row['end_turn']} "
            f"llm={'yes' if llm else 'no'}"
        )
        if llm:
            ep = llm.get("episode") or {}
            title = (ep.get("title") or "").strip()
            if title:
                print(f"    llm episode title: {title}")
            for op in llm.get("memoryOps") or llm.get("memory_ops") or []:
                print(
                    f"    llm op: {op.get('op')} {op.get('type')} "
                    f"{op.get('key')} = {op.get('value')} "
                    f"(src={op.get('sourceMessageIds') or op.get('source_message_ids')})"
                )
    print(f"\nlog path: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

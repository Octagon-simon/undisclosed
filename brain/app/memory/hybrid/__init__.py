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

"""Hybrid conversational memory (``hybrid_memory.md``).

Layer map:

    schema      records (Episode, StructuredMemory, WorkingMemory, ops, results)
    storage     filesystem sidecars + validated memory mutation (§10-13)
    text        tokenization, entities, BM25 (pure)
    lexical     BM25 + exact retrieval over raw messages (§17)
    vector      chromadb episode index (§16)
    extractor   boundary-aware episodes + memory-op proposals (§6-14, §29)
    llm_extract optional model pass: episode draft + MemoryOps (gated, §9/§12/§29-30)
    router      deterministic routing + escalation (§18, §22)
    ranking     hybrid score + rerank (§21)
    assembler   tagged, budgeted context (§24-27)
    engine      parallel retrieval + async run-end pipeline (§19, §28)

The whole layer is additive and gated behind ``UNDISCLOSED_HYBRID_MEMORY``; the
proven rolling-summary path keeps serving until the hybrid retrieval is
evaluated.
"""

from app.memory.hybrid import (
    assembler,
    canonical,
    config,
    engine,
    extractor,
    jobs,
    lexical,
    llm_extract,
    project,
    ranking,
    resolver,
    router,
    schema,
    storage,
    text,
    vector,
)
from app.memory.hybrid.engine import (
    build_context,
    drain_memory_jobs,
    load_events,
    process_run_end,
    retrieve,
    schedule_process_run_end,
)
from app.memory.hybrid.schema import (
    LEVEL_BROAD,
    LEVEL_EPISODES,
    LEVEL_EXACT,
    LEVEL_MEMORY,
    LEVEL_RECENT,
    ConversationRef,
    Episode,
    EpisodeDraft,
    ExtractionResult,
    MemoryJob,
    MemoryOp,
    Project,
    RetrievalPlan,
    RetrievalResult,
    RetrievedItem,
    StructuredMemory,
    WorkingMemory,
)
from app.memory.hybrid.storage import HybridStore

__all__ = [
    "LEVEL_BROAD",
    "LEVEL_EPISODES",
    "LEVEL_EXACT",
    "LEVEL_MEMORY",
    "LEVEL_RECENT",
    "ConversationRef",
    "Episode",
    "EpisodeDraft",
    "ExtractionResult",
    "HybridStore",
    "MemoryJob",
    "MemoryOp",
    "Project",
    "RetrievalPlan",
    "RetrievalResult",
    "RetrievedItem",
    "StructuredMemory",
    "WorkingMemory",
    "assembler",
    "build_context",
    "canonical",
    "config",
    "drain_memory_jobs",
    "engine",
    "extractor",
    "jobs",
    "lexical",
    "llm_extract",
    "load_events",
    "process_run_end",
    "project",
    "ranking",
    "resolver",
    "retrieve",
    "router",
    "schedule_process_run_end",
    "schema",
    "storage",
    "text",
    "vector",
]

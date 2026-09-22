# Grep / file-search tool efficiency — findings

**Status:** investigation notes + **P0 implemented (2026-09-21)**. The central
model-context tool-result bound is done (see below); the rg/ignore/pagination
rewrite is the follow-up.

## Implementation status

- **[DONE] P0 — central model-visible tool-result bound.** `ListenChatAgent`
  (`app/agent/listen_chat_agent.py`) now overrides `_record_tool_calling` and
  middle-truncates any result whose serialized form exceeds
  `UNDISCLOSED_MAX_TOOL_RESULT_CHARS` (default 8000) — head + marker + tail —
  BEFORE CAMEL records it into memory. Tool-agnostic (fixes grep, `search_files`,
  `glob_files`, and any future offender); truncates content only, never splits
  the tool_calls/tool pair. CAMEL's own `_truncate_tool_result` was near-useless
  (only fires at ~90% of the whole context window). Needs a brain restart.
- **[LATER] P1+ — follow the research order** (`research-ans-grep.md`):
  2. rg-backed grep/search with a Python fallback (runtime `shutil.which('rg')`;
     the brain's Docker image ships without rg — add `ripgrep` to `brain/Dockerfile`
     for the fast path there). 3. default ignored dirs / binary exclusion in our
     `FileToolkit` subclass. 4. per-line + total caps with a "N more" footer.
     5. pagination (offset/next_offset). 6. consistent bounds for glob/search/grep
     + drop `search_files`'s `["md"]` default & unbounded JSON. 7. prompt steer to
     `code_query` (find_symbol/find_references/context_at) over grep. 8. MEASURE
     the sync `_execute_tool` path before changing it. 9. caching last.

---

**Original status:** investigation notes. Nothing here is implemented. This file
exists so the finding is written down before any fix is chosen.

**Question investigated:** the file-search tool "works, but it's inefficient — it
runs so many searches before finding what it wants, and even then the output is
so verbose it can push the LLM into 'token limit exceeded'."

That description is accurate, and the cause is specific. Below: exactly how the
tool is wired, exactly what it returns, and exactly why it is both slow and
token-heavy.

---

## 1. What "our grep tool" actually is

We do **not** ship a grep tool. The agent calls CAMEL's `FileToolkit.grep_files`
(and `search_files`, `glob_files`), exposed through our subclass
`brain/app/agent/toolkit/file_write_toolkit.py::FileToolkit`.

- Our subclass overrides only `read_file` and `write_to_file`.
  `grep_files`, `search_files`, `glob_files`, `edit_file`, `notebook_edit_cell`
  are **inherited unchanged** from CAMEL's `FileToolkit.get_tools()`
  (vendored at `brain/.venv/.../camel/toolkits/file_toolkit.py`).
- Assembly: `brain/app/agent/factory/toolkit_assembler.py` builds the `file`
  toolkit (`_enabled(config, "file")`, ~line 482) and registers its tools under
  the toolkit name `file` (line 502).
- Exposure: `brain/app/agent/tool_rag.py` lists `"file"` in
  `_CORE_TOOLKIT_MARKERS` (lines 48-67), so **the file tools are always exposed**,
  independent of tool-RAG routing. The model can always reach `grep_files`.
- The system prompt actively points at grep
  (`brain/app/agent/prompt.py`, many lines: "grep the specific list", "use
  `grep` to search within them"). So the model is nudged toward the unbounded
  tool, not the bounded `code_query` one.

So "our grep tool calls" = CAMEL's `grep_files` / `search_files` / `glob_files`,
running under our process, with no brain-side override.

---

## 2. The exact call path

1. Model emits a `grep_files(pattern, path, ...)` tool call.
2. `ListenChatAgent._execute_tool` / `_aexecute_tool`
   (`brain/app/agent/listen_chat_agent.py`) runs it.
   - Async path: sync tools are hopped off the loop with `asyncio.to_thread`
     (line ~1113) so a long scan doesn't stall uvicorn.
   - Sync path (`_execute_tool`, line ~921): the tool is called **inline on the
     event loop**. A repo-wide recursive scan on this path blocks the whole
     brain (the "brain went deaf" class of bug).
3. The returned string is stored verbatim into agent memory via
   `_record_tool_calling(...)`, and re-sent to the model on the next step.
4. Only a *narration* copy is truncated (see §5).

---

## 3. `grep_files` — signature and defaults

From CAMEL `file_toolkit.py` (`def grep_files`, ~line 1333):

```
grep_files(
    pattern: str,                 # required
    path: str,                    # REQUIRED directory to search recursively
    glob_pattern: str = "*",
    file_type: Optional[str] = None,
    output_mode: str = "content",  # content | files_with_matches | count
    ignore_case: bool = False,
    context_lines: int = 0,
    head_limit: int = 20,
    multiline: bool = False,
)
```

Defaults that matter:

- **`path` is mandatory.** The model must already know where to search, so when
  it doesn't, it greps the repo root.
- **`head_limit=20`** caps *blocks* in `content` mode only.
- **`glob_pattern="*"`** means "walk everything".
- `content` mode joins blocks with `"\n--\n"` (line ~1471).

### Algorithm

`_iter_grep_candidate_files(root, glob_pattern, file_type)` (~line 140):

```python
for candidate in root.rglob(glob_pattern):   # FULL recursive walk
    if not candidate.is_file(): continue
    if suffix and candidate.suffix.lower() != suffix: continue
    candidates.append(candidate)
return sorted(candidates)
```

Then for each candidate it reads the **entire file** as text (`read_text`,
errors="ignore") — skipping only files larger than 2 MB (line ~1399) — and
regex-scans line by line.

The critical gap: **there is no ignore handling at all.** No `.gitignore`, no
default excludes. A search from the repo root walks `node_modules/`, `.git/`,
`brain/.venv/` (tens of thousands of files), `lib/`, `dist/`, `build/`,
`.cache/`, etc. It reads every one.

### Output rendering

Each match becomes a block (`_render_grep_context_block`, ~line 159):

```
/path/to/file.py:42:> the matched line, rstripped
```

Blocks are joined with `\n--\n`. In `content` mode, if there are more than
`head_limit` matches the string **just stops at 20 blocks — with no "showing 20
of N" footer**. `files_with_matches` returns a list slice; `count` returns a
dict.

---

## 4. The siblings

- **`search_files`** (~line 1600): case-insensitive **substring** search.
  - Default `file_types=["md"]` — it searches *only markdown* unless told
    otherwise. Surprising default.
  - Returns `json.dumps(result, indent=2)` containing **every** match, **no
    limit parameter at all**. This is the most dangerous of the three: an
    unbounded, pretty-printed JSON blob.
- **`glob_files`** (~line 1302): `root.glob(pattern)` (non-recursive unless the
  pattern has `**`). Returns a list of absolute paths, no cap.

---

## 5. The truncation gotcha (why the output reaches the model unbounded)

`brain/app/agent/listen_chat_agent.py` has a `MAX_RESULT_LENGTH = 500` cap
(lines ~933-945 sync, ~1151-1163 async). Read it carefully:

```python
if isinstance(result, str):
    result_msg = result            # string: passed through VERBATIM
else:
    result_str = repr(result)
    if len(result_str) > 500:
        result_msg = result_str[:500] + "...(truncated...)"
    else:
        result_msg = result_str
...
return self._record_tool_calling(func_name, args, result, ...)  # FULL result
```

Two facts:

1. **`result_msg` is the UI narration only** (the SSE "deactivate toolkit"
   event). What goes to memory, and therefore back to the model, is `result`
   (the full, untruncated value).
2. **String results are never truncated at all.** `grep_files` and `search_files`
   return strings, so they bypass the 500-char cap entirely.

And there is nothing downstream to catch it:

- The memory **window is disabled by default** —
  `agent_model._memory_window_size()` reads `UNDISCLOSED_AGENT_MEMORY_WINDOW`,
  default `"0"` (off), deliberately, because a message-count window can split a
  `tool_calls`/`tool` pair and 400 the request.
- The token-management doc's "tool-result truncation = 500" line
  (`docs/systems/token-management.md` §8) is therefore **only a UI-narration
  guard**, not a context guard. Worth correcting the impression.

Net effect: one repo-wide `grep_files` returning 20 fat blocks (a matched
minified line can be thousands of chars, since there is no per-line cap, and
files up to 2 MB are read whole) lands in memory in full and is **re-sent on
every subsequent step of the turn** — and, at turn boundaries, folded into the
rolling summary path until compaction. That is the "token limit exceeded".

---

## 6. Every other file-ish tool is bounded; these three are not

For contrast, the brain-side tools that fan out over files all have explicit
caps:

| Tool | Cap | Where |
| --- | --- | --- |
| `read_file` | 2 MB, then truncate-with-marker | `file_write_toolkit.py` `_MAX_TEXT_BYTES` |
| `code_query` (`find_symbol`, `find_references`, `context_at`, ...) | 200 results, middle-truncated to 4000 chars | `code_query_toolkit.py` `_MAX_RESULTS`, `_MAX_CONTEXT_CHARS` |
| `understand_project` | 60 000 chars | `project_context_toolkit.py` `_MAX_DIGEST_CHARS` |
| git | 20 000 chars | `git_toolkit.py` `_MAX_OUTPUT_CHARS` |
| test runner | 20 000 chars | `test_runner_toolkit.py` `_MAX_OUTPUT_CHARS` |
| **`grep_files` / `search_files` / `glob_files`** | **none** | CAMEL `file_toolkit.py` |

So a fix that belongs to this codebase already has a shape to copy:
`code_query_toolkit._truncate_middle` + `_MAX_RESULTS` / `_MAX_CONTEXT_CHARS`.

---

## 7. Why "so many searches"

The repeated-search behaviour falls out of the design, not the model being
lazy:

1. **Vendored-tree pollution.** A root grep returns matches from `node_modules`,
   `.venv`, `lib`, etc. The signal is buried, so the model narrows and re-greps.
2. **`path` is required and there is no default.** When the model doesn't know
   the subtree, it guesses; a wrong guess = a wasted call, then another.
3. **No pagination.** `content` mode returns 20 blocks and stops with no
   "N more" hint, so to see more the model must re-issue a different query.
4. **No caching/index.** Every call re-walks the tree from scratch (unlike
   `understand_project`, which caches per git HEAD).
5. **Wrong tool nudged.** The prompt pushes grep; the bounded structural tool
   (`code_query`) exists but isn't positioned as the preferred path.
6. **Slow calls cause retries.** A root walk over `.venv` can take seconds to
   tens of seconds; on the inline sync path it also stalls the loop, and a
   timeout/failure invites a retry.

---

## 8. Optimization options (unranked; pick for the research)

All of these can live in **our** `FileToolkit` subclass (override the methods),
mirroring the existing `read_file` override, so we are not patching the vendored
CAMEL package.

**A. Default excludes + ignore rules (highest impact, lowest risk).**
Override `_iter_grep_candidate_files` (or the three public methods) to prune
`.git`, `node_modules`, `.venv`, `dist`, `build`, `lib`, `target`, `.cache`,
`vendor`, `*.min.js`, etc. before descending, and optionally honor `.gitignore`
via `pathspec`. This alone kills both the slowness and the dependency-polluted
results. (repomix already applies ignore semantics, so there's precedent/a
dependency already in play.)

**B. Hard output caps that the model can see.** Per-line cap (~400 chars),
total-chars cap (~8k), and a footer like
`[showing 20 matches in 6 files; refine the pattern or raise head_limit]`.
Middle-truncate like `code_query._truncate_middle`.

**C. Make `path` optional** (default to the working directory) and consider
defaulting `glob_pattern` to a text/code set so binary and huge data files never
enumerate.

**D. Prefer ripgrep when present.** Shell out to `rg --json`/`-c` with
`--max-count`, falling back to the Python walker. Faster, already ignore-aware,
and bounded. Caveat: `rg` may not be installed in every deployment.

**E. Pagination/offset** plus a summary line, so "show me more" is one call
instead of a fresh empty-handed search.

**F. Steer the model to the bounded tool.** Add a short prompt line ("prefer
`find_symbol`/`find_references`/`context_at`; use `grep_files` only as a
fallback") and/or make file-grep reachable via `understand_project` rather than
always-on.

**G. Fix `search_files`.** Drop the `["md"]` default, add a result limit, and
stop pretty-printing JSON for a 200-row blob.

**H. Cache.** An mtime-keyed result cache (like the project-context digest) so
repeat greps in a turn don't re-walk.

---

## 9. Caveats / open questions

- Overriding `_iter_grep_candidate_files` is a **private** CAMEL method; a CAMEL
  bump could rename it. Keeping the override in our subclass (not the venv)
  contains the blast radius, but it is still a dependency-internal hook.
- A `.gitignore`-honoring scan needs a matcher (`pathspec`); a fixed
  dir-name exclude list is simpler but coarser.
- Aggressive truncation risks hiding the one match the model needed; the footer
  in (B) is what makes truncation safe.
- The sync `_execute_tool` inline path (line ~921) is a separate latency/hang
  risk for any heavy scan; confirm which path real turns take before assuming
  `asyncio.to_thread` protects us.
- Exact CAMEL version/paths should be re-confirmed against the pinned dependency
  when implementing (this doc cites the tree as of writing).

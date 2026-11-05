# Chat attachments

Attaching a file to a chat has to keep working across a page reload, a new chat,
a brain restart, and the brain minting a session for requests that arrive without
one. This doc covers the path a file takes, why the upload session is baked into
the ref, and the limits that path enforces.

Code: `brain/app/controller/file_controller.py`,
`brain/app/utils/file_utils.py`, `agent-ui/src/api/http.ts`,
`agent-ui/src/lib/attachmentUrl.ts`.

---

## The path a file takes

1. **Client upload.** The chat box posts `multipart/form-data` to `POST /files`
   with `X-Session-ID` when it has one (`uploadFileToBrain` in `http.ts`).
2. **Brain files it under a session.** The endpoint takes the header, or falls
   back to `request.state.session_id` (the session the middleware minted for
   that request). It validates the id against `SESSION_ID_PATTERN`, enforces
   the size and count limits below, and writes the bytes to
   `~/.undisclosed/workspace/<session>/uploads/<safe_name>_<epoch_ms>`.
3. **Brain returns a session-scoped ref.** `file_id` is
   `upload://<session>/<stored_name>`. The ref is what the message stores and
   what the agent reads.
4. **Client renders it.** `attachmentUrl.ts` turns the ref into
   `<brain>/files/upload-content?file_id=...&session_id=...`. The session goes
   in the query string, not the header, because an `<img src>` bypasses the
   header wrapper.
5. **Brain serves the bytes.** `GET /files/upload-content` prefers the session
   inside the ref, falls back to the `session_id` query param, then falls back
   to a store-wide lookup by stored name. Stored names are unique (they carry a
   millisecond timestamp), so exactly one file matches. Traversal still 404s.
6. **Agent resolves the ref.** `resolve_upload_ref` in `file_utils.py` takes the
   same three steps when the agent opens an attachment: ref session, then glob.

## Why the session lives in the ref

The ref used to be just `upload://<name>`, which assumed the upload session and
the chat session were the same. They were not: `ConnectionContext` only primed
a session for the `web` channel, the panel mounts as `desktop`, and the brain
mints a fresh session per request that has no `X-Session-ID`. Uploads landed
under session A, the chat ran under session B, and the content lookup in the
wrong directory returned `404 File not found`.

Two things keep them aligned now: the panel primes a session for every channel,
and `persistSessionIdFromResponse` is first-write-wins so the connection session
stops flapping. The ref still carries its own session, because a reload or a new
chat changes the connection session while the bytes stay where they were
written.

Refs written before this change (`upload://<name>`) still resolve through the
store-wide fallback, so old chat history keeps working.

## Limits

Both constants are at the top of `file_controller.py`.

| Limit | Value | Constant | Response |
| --- | --- | --- | --- |
| Max size per file | 50 MB | `MAX_FILE_SIZE_BYTES` | `413` |
| Max files per session | 20 | `MAX_FILES_PER_SESSION` | `429` |

**`MAX_FILES_PER_SESSION = 20`** is counted by entries in
`<workspace>/<session>/uploads`, so the cap is per chat session, not per
project: a new chat starts with a fresh 20. It is a flat count of files, not
bytes.

This only became reachable after sessions stopped drifting. Before the fix,
uploads scattered across freshly minted sessions, so one chat seldom accumulated
20 in one directory. Now a long chat with many attachments will hit
`Maximum 20 files per session`. Raise the constant in `file_controller.py` if
that turns out to be too tight for real use; there is no env override.

## Caveats

- The desktop (Electron) path can still open absolute local paths through
  `electronAPI.readFileAsDataUrl`. `attachmentUrl.ts` covers the web/embed path;
  the two are not interchangeable.
- Uploads are not part of project history, so they do not appear in the file
  explorer or in `GET /files`.

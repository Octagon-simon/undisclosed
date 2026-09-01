# Assistant message persistence — Implementation notes

This change introduces API routes to persist assistant messages per user turn and wires the UI to rehydrate grouped turns from the server. It keeps the existing in-memory flow for instant UX and adds best-effort background POSTs with retry on transient failures.

Backend
- Controller: brain/app/controller/chat_history_controller.py (new)
- Service: brain/app/service/chat_history_service.py (new)
- Model: brain/app/model/chat_history.py (new)
- Router registration: brain/app/router.py (include router with same /api/v1 prefix)
- Tests: brain/tests/app/controller/test_chat_history_controller.py

Routes
1) POST /api/v1/chat/{chatId}/turns/{queryId}/messages
   - Body: { role: 'assistant' | 'user', message: { id, step, content, reasoning?, attaches?, fileList?, agent_name?, createdAt } }
   - Behavior: role=assistant -> upsert turn; append to otherMessages. role=user -> upsert turn.userMessage
   - Returns: the updated turn object

2) GET /api/v1/chat/{chatId}/turns
   - Returns: ordered array of { chatId, queryId, userMessage, otherMessages }

3) GET /api/v1/chat/{chatId}/turns/{queryId}
   - Returns: the single turn object

Storage
- Reuse the existing LocalMemoryStore root under ~/.eigent/memory as a pragmatic store for desktop mode, writing JSONL per chatId turn. Layout:
  ~/.eigent/memory/turns/<chatId>/turn_<queryId>.json
- The file holds a single JSON document with the turn shape; updates rewrite atomically.
- This coexists with conversation.jsonl (durable project memory) and doesn’t change chat runtime behavior.

Frontend
- agent-ui/src/store/chatStore.ts: enqueue POST when appending any assistant message; keep the local store update first for UX.
- agent-ui/src/components/ChatBox/ProjectSection.tsx: on mount for an active chat, GET turns and stitch into grouped view; merge by message id to avoid duping already-present SSE-replayed lines.
- Simple in-memory retry queue per chatId/queryId; drop item after success.

Work-log visibility
- agent-ui/src/components/ChatBox/MessageItem/TaskWorkLogAccordion.tsx: add console.debug traces in buildAgentBlocks and InlineMessageRow render.

Notes
- Header detection for persisted context remains heuristic ("Persisted Project Context" and "<remembered_facts>").
- This patch is self-contained; swap the storage implementation (e.g., DB) behind chat_history_service if needed later.

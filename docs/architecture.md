# Architecture Decision Records

## ADR-001: Local-first, single-user design

**Decision**: All data (SQLite DB, files) stays on the user's machine. No cloud sync in MVP.

**Reasoning**: Privacy, simplicity, offline capability.

---

## ADR-002: FastAPI over Node backend

**Decision**: Python FastAPI for the orchestrator.

**Reasoning**: Python has the best ecosystem for AI/ML tools (pypdf, python-docx, pptx, future LangChain/LlamaIndex integration).

---

## ADR-003: Keyword-based intent classification in MVP

**Decision**: Use regex-based intent parsing for v1 rather than an LLM.

**Reasoning**: Zero API dependency for MVP. Swap `_classify_intent()` in `command_router.py` with an LLM function-calling parser when an API key is available.

---

## ADR-004: Approval queue for destructive actions

**Decision**: `move_file` and `sort_downloads` require explicit user approval.

**Reasoning**: These actions move or reorganise potentially important files. Silent execution could cause data loss.

---

## ADR-005: Playwright hook (not implemented)

**Decision**: Leave `memory_service.py` and a placeholder in the tool registry for future browser automation.

**Reasoning**: Web research requires careful sandboxing and terms-of-service review. Deferred to v2.

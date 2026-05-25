# Plan: Fix Per-Episode Summary Truncation

**Status**: In Progress
**Created**: 2026-05-26
**Last Updated**: 2026-05-26

**CRITICAL INSTRUCTIONS**: After completing each phase:
1. ✅ Check off completed task checkboxes
2. 🧪 Run all quality gate validation commands
3. ⚠️ Verify ALL quality gate items pass
4. 📅 Update "Last Updated" date
5. 📝 Document learnings in Notes section
6. ➡️ Only then proceed to next phase

⛔ DO NOT skip quality gates or proceed with failing checks

---

## Problem

Per-episode summaries are truncated mid-word, even after raising
`max_output_tokens` from 600 → 2500. Observed in `youtube-digest-archive/src/content/issues/2026-05-26.md`:

- English: ends with `"...much like early"` (no period, mid-sentence)
- English: ends with `"...expecting awkward"` (no period, mid-sentence)
- Korean: cut even shorter

## Root Cause

Gemini 2.5 Flash has **"thinking" mode enabled by default**. Thinking tokens
are counted against `max_output_tokens`. With a 2500-token cap, thinking
consumes ~2000 tokens, leaving only ~500 for the actual summary text —
roughly the observed ~400-char English cutoff.

Bumping the cap further is wasteful: the model just thinks more. Summary
generation is a focused extraction task that does not benefit from
extended reasoning.

## Fix Strategy

1. **Disable thinking** (`thinking_budget=0`) for summary calls.
2. **Right-size the cap** at 4000 tokens — enough for a 500-800 char
   Korean summary with margin.
3. **Detect truncation** via `finish_reason` and `usage_metadata`, log
   it, and auto-retry with a doubled cap.
4. **Graceful fallback**: if a retry still truncates, cut at the last
   complete sentence boundary instead of mid-word.

---

## Phase 1: Diagnostic Logging & Test Harness (RED)

**Goal**: Make truncation visible and write tests that fail against the
current implementation.

**Test strategy**: Unit tests with a mocked Gemini client that returns
canned responses (truncated, complete, missing usage_metadata).

### Tasks
- [x] **RED**: Add unit tests asserting that `generate_summary()`:
  - logs `usage_metadata` (prompt / candidates / thoughts tokens) when present
  - flags `finish_reason == MAX_TOKENS` as truncated
  - returns the text even when truncated (so we don't lose partial output)
- [x] Add `_log_usage_metadata()` helper to `write_articles.py`
- [x] Tighten `finish_reason` detection (handle enum, string, and int forms)

### Quality Gate
- [x] New tests run and fail meaningfully against current code
- [x] No existing tests broken
- [x] `py -m pytest -v` green for unchanged tests

---

## Phase 2: Disable Thinking & Right-Size Token Cap (GREEN)

**Goal**: Eliminate the actual truncation source.

### Tasks
- [x] **GREEN**: Add `thinking_config=types.ThinkingConfig(thinking_budget=0)` to the summary `GenerateContentConfig`
- [x] Bump `max_output_tokens` 2500 → 4000 (room for a long Korean summary even without thinking)
- [x] Verify config payload via unit test
- [x] Phase 1 tests now pass for the "complete response" case

### Quality Gate
- [x] All unit tests pass
- [x] Config object includes `thinking_config` with `thinking_budget=0`
- [x] No regression in existing `test_export_archive.py`

---

## Phase 3: Auto-Retry & Sentence-Boundary Fallback (REFACTOR)

**Goal**: Defense-in-depth so a future change doesn't silently truncate.

### Tasks
- [x] **REFACTOR**: When `finish_reason == MAX_TOKENS`, retry once with `max_output_tokens * 2`
- [x] If still truncated, trim to the last complete sentence (period/Korean `다`/`요`/`.` boundary)
- [x] Unit test: truncated response → retry path invoked → final output ends at sentence boundary
- [x] Unit test: complete response → no retry, no trimming

### Quality Gate
- [x] All tests pass
- [x] Truncation cannot leak into archive output silently
- [x] Logging clearly distinguishes: complete / truncated-retried / truncated-trimmed

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `thinking_config` not supported by installed SDK version | Low | High | Verify `google-genai` version; wrap in try/except and fall back to original config |
| Disabling thinking degrades summary quality | Low | Medium | Summary is extractive; thinking unlikely to help. Compare a few outputs after change |
| 4000 tokens still insufficient for unusual transcripts | Low | Medium | Phase 3 auto-retry doubles cap |
| Sentence-boundary trim removes legitimate content | Low | Low | Only triggered after retry exhausts; clearly logged |

## Rollback Strategy

- Single commit per phase
- Revert via `git revert <commit>` — no data migrations or external state changes
- Archive issues already generated are not affected; fix applies to future runs

## Notes & Learnings

- **Lesson**: With Gemini 2.5 Flash, `max_output_tokens` is *not* an output-text budget — it's a total budget shared with thinking. For deterministic-length extraction tasks, set `thinking_budget=0`.
- The previous fix (bumping tokens 600→2500) didn't help precisely because thinking expands to fill available budget.

# Plan: Surface Episode Summary in TOC + Shorten to 2 Paragraphs

**Status**: In Progress
**Created**: 2026-05-27
**Last Updated**: 2026-05-27

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

1. **TOC omits summary**: the left-sidebar TOC at `youtube-digest-archive/src/pages/issues/[...slug].astro` picks up `h1, h2, h3` only. The current summary block uses a bold paragraph (`**Episode summary**`), so it never appears in the left index.
2. **Summary too long**: observed three-paragraph summaries; user wants ~2 paragraphs.

## Strategy

1. Move the summary INSIDE the article body, right after the first H1, as an `### Episode summary` / `### 에피소드 요약` heading. This places it as a child of the article's H1 group in the mobile TOC, and as a flat-level-3 entry in the desktop TOC.
2. Tighten the prompt to demand exactly two paragraphs at shorter target length.

## Phase 1: Surface Summary in TOC (RED → GREEN)

**Goal**: `### Episode summary` / `### 에피소드 요약` lands right after the article's first H1, so the TOC includes it without the article losing its current grouping.

### Tasks
- [ ] **RED**: Add tests for `_inject_summary_after_h1()`:
  - H1 present → H3 heading + body inserted immediately after H1
  - No H1 → fallback prepends so summary is never lost
  - Multiple H1s → inject after the FIRST H1 only
  - Empty summary → article text unchanged
  - Korean label `### 에피소드 요약` used when `label='ko'`
  - English label `### Episode summary` used when `label='en'`
- [ ] **RED**: Update `test_export_archive.py` integration test: confirm body no longer carries `**Episode summary**` literal; instead carries `### Episode summary` AFTER a `# ` H1
- [ ] **GREEN**: Implement `_inject_summary_after_h1()` in `export_archive.py`
- [ ] **GREEN**: In `generate_issue_markdown()`, route summary through the new helper instead of prepending a bold block

### Quality Gate
- [ ] All new unit tests pass
- [ ] Existing 15 `test_export_archive.py` tests updated and pass
- [ ] Existing 22 `test_write_articles_summary.py` tests still pass
- [ ] Verify rendered markdown by reading a regenerated `.md` and confirming structure

---

## Phase 2: Tighten Summary to 2 Paragraphs (REFACTOR)

**Goal**: Summary fits comfortably in the TOC-anchored block without scrolling.

### Tasks
- [ ] **REFACTOR**: Rewrite prompts in `generate_summary()`:
  - Target length: Korean 300-500 chars / English 400-700 chars
  - Required structure: exactly 2 paragraphs, blank line between
    - Paragraph 1: topic + central claim + 1-2 specific pieces of evidence (numbers, names)
    - Paragraph 2: practical takeaway, nuance, or caveat
  - Keep banned-phrases list and style rules
- [ ] Optional: keep `max_output_tokens=4000` (already plenty for 500 chars even with thinking_budget=0)
- [ ] Run existing tests — should all still pass since they mock responses

### Quality Gate
- [ ] All tests pass
- [ ] Manual: regenerated summary visibly shorter (eyeball check on next live run)

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Existing archive issues already shipped with old layout | High | Low | Old issues stay as-is; only new runs use new layout |
| H3 heading visually clashes with article body sections | Low | Low | Site CSS treats all H3s consistently; can refine styling later |
| Mobile TOC grouping breaks if H1 normalization fails | Low | Medium | `_normalize_article_headings` already guarantees one H1; tests confirm |
| Prompt change reduces content depth too far | Low | Medium | Specific char-length targets preserve substance; manual review on first run |

## Rollback Strategy

Each phase is one commit. Revert via `git revert <sha>`. No data migrations. Already-shipped archive issues are untouched.

## Notes & Learnings

(populated as phases complete)

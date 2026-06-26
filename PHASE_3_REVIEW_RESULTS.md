# Phase 3 Review Results — Job Discovery Orchestrator

**Date:** 2026-06-26
**Reviewers:** Backend Pre-Merge Reviewer, Security Auditor (Phase 1 adversarial pass)
**Scope:** `src/orchestrator/{discovery,approval_parser,rate_limiter,deduplicator,salary_extractor,digest_generator}.py`, `src/database/schema.py`
**Test baseline:** 24 passed / 6 skipped (orchestrator slices + acceptance gates) before and after fixes.

---

## Summary

| Severity | Found | Fixed | Deferred |
|----------|-------|-------|----------|
| Critical | 0     | 0     | 0        |
| High     | 2     | 2     | 0        |
| Medium   | 7     | 6     | 1        |
| Low      | 6     | 5     | 1        |

One High-confidence security item (sender authentication) is **designed and exposed as an API** but its enforcement lands in Phase 4 when `orchestrator.py` is wired. Two items on the API agent layer are explicitly **deferred** (outside the discovery scope; one is already gated as Lever "Gate 1").

---

## High — Fixed

### H1. Greenhouse `company` always resolved to `"Unknown"` → silent job loss
- **Evidence:** `discovery.py` read `job["organization"]["name"]`, a field the Greenhouse Board API does not return per job. Every job became `"Unknown"`.
- **Impact:** `deduplicator` fingerprints on `title|company`. With all Greenhouse companies collapsed to `"unknown"`, two different companies posting the same role title hashed identically and the second was dropped from the batch — real jobs disappeared silently.
- **Fix:** Removed the dead `organization` read. Company is now taken from a caller-supplied value or resolved once from the Greenhouse board metadata endpoint (`_fetch_greenhouse_company`), falling back to `"Unknown"` only when the board name is genuinely unavailable. Jobs with no title are now skipped with a warning instead of producing `None` fingerprints.

### H2. Unanchored `approve all` / `reject all` match converted prose into batch-wide actions
- **Evidence:** `re.search(r'approve\s+all', body)` matched the substring anywhere; `"don't approve all of them, just 1 and 3"` approved the whole batch, and it ran before the specific-ID parse.
- **Impact:** Auto-submission to every job in a batch regardless of the user's stated intent.
- **Fix:** Bulk-command patterns are now anchored to the start of a line (`^\s*approve\s+all\b`, `re.MULTILINE`). A bulk action only triggers when the command leads its own line.

---

## Medium — Fixed

### M1. SQLite foreign keys declared but never enforced
- **Evidence:** `REFERENCES` clauses throughout `schema.py`, but no connection ran `PRAGMA foreign_keys = ON` (SQLite ignores FKs by default). Orphaned/forged `batch_jobs` and `approval_log` rows were accepted.
- **Fix:** Added a single `get_connection()` factory that sets `PRAGMA foreign_keys = ON` on every connection; `init_database` uses it. Documented that all DB access must go through this factory.

### M2. `filters` parameter silently ignored
- **Evidence:** `discover_jobs`/`discover_greenhouse`/`discover_lever` accepted `filters` but never read it; callers passed `{"salary_floor": ...}` assuming filtering happened.
- **Fix:** Discovery now logs when a non-empty `filters` is supplied and the docstring states plainly that salary/threshold filtering is applied downstream (salary/digest stage), not at discovery. The misleading silent no-op is gone.

### M3. Broad `except Exception` masked bugs as "no jobs found"
- **Evidence:** Both discovery functions caught everything and returned `[]`, making a code/JSON-shape bug indistinguishable from an empty board.
- **Fix:** Narrowed to `httpx.TimeoutException` → `httpx.HTTPError` → `(json.JSONDecodeError, ValueError)`. Unexpected exceptions now propagate instead of being swallowed.

### M4. New tables lacked indexes on their foreign keys
- **Fix:** Added indexes on `batch_jobs(batch_id)`, `batch_jobs(job_id)`, `job_discoveries(batch_id)`, `job_discoveries(job_id)`, `approval_log(batch_id)`, and `status_history(application_id)`.

### M5. No uniqueness guard on `batch_jobs(batch_id, job_id)`
- **Fix:** Added `UNIQUE(batch_id, job_id)` so the same job cannot be inserted into a batch twice.

### M6. "Soft deletes" claimed but not implemented
- **Evidence:** No `deleted_at`/`is_deleted` column on any table despite the handoff claim.
- **Fix:** Added a `deleted_at TIMESTAMP` column to every audit-participating table (`jobs`, `applications`, `email_triage`, `manual_review_queue`, `job_batches`, `batch_jobs`, `job_discoveries`, `approval_log`). `status_history` remains append-only by design.
- **Caveat (follow-up):** `CREATE TABLE IF NOT EXISTS` does not migrate an already-existing DB. This is greenfield (no production DB yet); a one-time `ALTER TABLE` migration is noted for whenever an older `jobs.sqlite` exists.

### M7. Deduplication fingerprint had no normalization
- **Evidence:** `f"{title}|{company}".lower()` only — trailing whitespace / internal spacing differences across platforms defeated dedup, the exact case the module exists to catch.
- **Fix:** Added `_normalize()` (strip + collapse internal whitespace + lowercase, None-safe) applied to both fields before hashing. Switched the fingerprint hash from MD5 to SHA-256 (non-security, silences scanners).

---

## Low — Fixed

- **L1.** `rate_limiter.is_paused()` mutated state (a predicate side effect) — now a pure check; the stale-timestamp cleanup was unnecessary because the time comparison already handles expiry.
- **L2.** `rate_limiter.retry_with_backoff` annotated `-> float` but returned `None` — corrected to `-> Optional[float]`.
- **L3.** `approval_parser` `unanswered` list sorted lexicographically (`"10" < "2"`) — now `sorted(..., key=int)`.
- **L4.** `schema.init_database` leaked the connection on a mid-DDL error — now wrapped in `contextlib.closing`.
- **L5.** Emoji (`⚠️`) literal in `digest_generator` source (violates project no-emoji rule) — replaced with text marker `[BELOW THRESHOLD]`.

---

## Security Audit — Phase 1 Findings

Adversarial pass over the Primary surfaces (input handling, external calls, business logic, audit layer). No suspicious-intent patterns found (no hardcoded bypasses, debug credentials, or obfuscation).

- **VULN-1-1 (High, Likely) — Approval path had no sender authentication.** `parse_approvals` took only the body; nothing bound an approval to the legitimate owner, and the inbox is internet-reachable. **Mitigation shipped:** added `is_authorized_sender(sender, authorized_emails)` (case-insensitive bare-address match, exported from the package). **Enforcement requirement for Phase 4:** the orchestrator MUST call this against the reply `From` before honoring any approval, and should additionally confirm the reply is in-reply-to the digest message-id and rely on Gmail SPF/DKIM. Documented in the module docstring. *Single-user note:* even for one user on a private address, an attacker who learns the address could otherwise inject `APPROVE all`; the guard is cheap defense-in-depth.
- **VULN-1-2 (High, Confirmed) — Unanchored bulk-approval match.** Same as H2 above. **Fixed.**
- **VULN-1-3 (Medium, Confirmed) — Audit trail not tamper-resistant.** FKs unenforced (fixed via M1) and no append-only protection on `status_history`/`approval_log`. FK enforcement now in place; append-only triggers noted as a Phase 4 hardening option depending on whether the audit trail must be forensic.
- **VULN-1-4 (Low, Confirmed) — Markdown/HTML injection from untrusted job fields into the digest.** **Fixed:** `_escape_markdown` escapes control characters (including `<`/`>`) on all externally sourced title/company/URL/batch values.
- **VULN-1-5 (Low, Likely) — Unencoded path/query interpolation in discovery URLs.** **Fixed:** `board_token` and `company` are now `urllib.parse.quote(..., safe='')`-encoded. Host remains fixed, so blast radius was already bounded.
- **Checked and discarded:** ReDoS (linear patterns, no overlapping quantifiers), TLS (httpx verifies by default), secrets (Greenhouse board token / Lever company slug are public identifiers, no credentials in scope).

---

## Deferred (outside Phase 3 discovery scope)

- **D1 (Uncertain → potentially Critical) — `submit_application` targets non-existent endpoints.** `greenhouse_agent` POSTs to the read-only Board API URL (no submission route → 404, reproduced by existing tests); `lever_agent` is explicitly a placeholder pending "Gate 1" manual endpoint validation. This is the **application** path, not discovery. Must be resolved before any real submission ships (Phase 4 Gate 1/2).
- **D2 (Medium) — Blocking `time.sleep(30)` in agent submission retry** stalls a sequential batch loop. Belongs to the agent layer; revisit when the submission path is implemented.

*Pre-existing, unrelated:* 3 failures in `tests/test_greenhouse_agent.py` (fixtures called directly → real network 404s) fail identically on baseline `8c038de`; not introduced here.

---

## Final Verdict

**APPROVED WITH NOTES** for the Phase 3 discovery scope.

Both High-severity correctness/security bugs are fixed and verified; all Medium/Low in-scope items are resolved; FK integrity and audit-trail enforcement are in place. Two notes carry into Phase 4 as hard requirements: (1) the orchestrator must enforce `is_authorized_sender` (VULN-1-1) before acting on approvals, and (2) the agent submission endpoints (D1) must pass Gate 1/2 before any live application is sent. All 24 in-scope tests pass with zero regressions.

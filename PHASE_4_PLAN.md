# Phase 4: Acceptance Testing & Implementation Gates — Handoff Plan

## Current Status

**Phase 1-2: COMPLETE ✓**
- MVP architecture implemented (Phase 1)
- Orchestrator with 10 TDD slices, all passing (Phase 2)
- 17/17 tests passing
- Comprehensive documentation created

**Phase 3: IN PROGRESS**
- Backend reviewer skill launched (awaiting findings)
- Manual review found 3 critical bugs, fixed all
- Rate limiter module ready for final review

**Phase 4: READY TO START**
- Acceptance tests need to be written and run
- Implementation gates (Gate 1, 2, 3) need validation
- End-to-end orchestrator workflow needs integration test

---

## What Happened

### Phase 1: Context & Research ✓
- Confirmed architecture: APIAgent + BrowserAgent abstractions
- Researched job discovery patterns, batch processing, email parsing
- Created CONTEXT.md with design decisions
- Documented field mapping YAML, database schema, error handling

### Phase 2: TDD Vertical Slices ✓
**Implemented 10 slices (17 tests, all passing):**
- Slice 1: Job discovery (Greenhouse, Lever APIs)
- Slice 2: Empty discovery edge case
- Slice 3-4: Salary extraction (regex patterns, normalization)
- Slice 5: Deduplication (MD5 hash, duplicate tracking)
- Slice 6-7: Approval parsing (email reply parsing, ID validation)
- Slice 8: Rate limiting (429 handling, exponential backoff)
- Slice 9: Timeout handling (graceful degradation)
- Slice 10: Error recovery (partial failure handling)

**Modules created:**
- `orchestrator/discovery.py` — Fetch jobs from APIs
- `orchestrator/salary_extractor.py` — Regex salary parsing
- `orchestrator/digest_generator.py` — Markdown email digest
- `orchestrator/approval_parser.py` — Parse user replies
- `orchestrator/deduplicator.py` — Detect duplicate jobs
- `orchestrator/rate_limiter.py` — Handle 429 rate limits
- `orchestrator/orchestrator.py` — [TODO] Main loop

**Database schema:** 4 new tables (job_batches, batch_jobs, job_discoveries, approval_log)

**Documentation:**
- ORCHESTRATOR_CONTEXT.md — Design decisions, field mapping, test matrix
- ORCHESTRATOR_ARCHITECTURE.md — Module overview, design patterns, integration plan

### Phase 3: Backend Review (In Progress)
- Manual review: Found 3 critical bugs (company field, ID validation, type hints) — all fixed
- Automated reviewer: Skill launched, awaiting findings
- Next: Review rate_limiter.py, then orchestrator.py integration

---

## Phase 3: Review Loop (CRITICAL — DO THIS FIRST)

### Step 1: Backend Pre-Merge Review
```bash
# Run backend-pre-merge-reviewer skill on:
# - orchestrator/*.py (all modules)
# - src/database/schema.py (new tables)
# Focus: error handling, API contracts, data validation, efficiency
```

### Step 2: Security Auditor Review
```bash
# Run security-auditor skill on:
# - orchestrator/approval_parser.py (regex injection risk)
# - orchestrator/discovery.py (credential handling)
# - orchestrator/rate_limiter.py (state management)
# Focus: OWASP, secrets, data flow, permissions
```

### Step 3: Fix All Findings
```bash
# Loop:
# 1. Review finds issues
# 2. Fix issues
# 3. Re-run reviews
# 4. Repeat until both agents return zero findings
```

---

## Phase 4: Acceptance Testing — After Reviews Pass

### Step 1: Write Acceptance Tests
**Create `tests/test_acceptance_orchestrator.py`** covering:

1. **End-to-end workflow:**
   - Discover 3 jobs from Greenhouse + Lever
   - Extract salaries (hourly, annual, range)
   - Generate markdown digest
   - User approves 2/3 jobs
   - System applies to approved jobs only
   - Verify applications created in DB

2. **Gate 1: Lever Endpoint Validation** (MANUAL)
   - Instructions: Test Lever endpoint manually before scaling
   - POST to `jobs.lever.co/{company}/{id}/apply`
   - Verify no CSRF/session required
   - If fails → move Lever to BrowserAgent tier

3. **Gate 2: Smoke Test 5/5**
   - 2 Greenhouse submissions (real credentials)
   - 2 Lever submissions (if Gate 1 passes)
   - 1 Ashby submission (Playwright, needs full implementation)
   - Verify: App created, email received, DB entry correct

4. **Gate 3: Regression Baseline**
   - 20 applications across platforms
   - Accept ≤20% failure rate
   - Verify failures not clustering on single platform

### Step 3: Implement orchestrator.py
**Create `src/orchestrator/orchestrator.py`:**
```python
class JobOrchestrator:
    def discover_and_digest(self, platforms: List[str]) -> Tuple[str, str]:
        # 1. Discover from all platforms
        # 2. Deduplicate
        # 3. Extract salaries + filter
        # 4. Generate digest
        # 5. Return (digest_content, batch_id)
        pass

    def apply_to_batch(self, batch_id: str, approved_job_ids: List[str]) -> dict:
        # 1. Get batch + approved jobs
        # 2. For each approved job, call agent.submit_application()
        # 3. Track results in DB
        # 4. Return summary
        pass

    def send_daily_reminder(self):
        # Poll for pending batches (>24h old)
        # Send email reminder to user
        # Update reminder_sent_at
        pass
```

### Step 4: Run Acceptance Suite
```bash
pytest tests/test_acceptance_orchestrator.py -v
# Expected: 5+ acceptance tests passing
# - End-to-end workflow ✓
# - Gate 1 instructions ✓
# - Gate 2 smoke test (skipped until credentials provided) [SKIP]
# - Gate 3 regression (follows Gate 2) [SKIP]
# - Email digest + approval flow ✓
```

### Step 5: Manual Testing
- Test discovery locally with real board tokens (if available)
- Test email digest generation and parsing
- Verify database state after batch approval

---

## Files & Paths Reference

**Core orchestrator modules:**
- `src/orchestrator/discovery.py` — Job discovery
- `src/orchestrator/salary_extractor.py` — Salary parsing
- `src/orchestrator/digest_generator.py` — Email digest
- `src/orchestrator/approval_parser.py` — Parse replies
- `src/orchestrator/deduplicator.py` — Deduplication
- `src/orchestrator/rate_limiter.py` — Rate limit handling
- `src/orchestrator/orchestrator.py` — [TODO] Main loop

**Database:**
- `src/database/schema.py` — Tables: job_batches, batch_jobs, job_discoveries, approval_log
- `data_folder/jobs.sqlite` — Database file

**Tests:**
- `tests/test_orchestrator_slices.py` — 17 TDD tests (all passing)
- `tests/test_acceptance_orchestrator.py` — [TODO] Acceptance tests

**Documentation:**
- `ORCHESTRATOR_CONTEXT.md` — Phase 1 context
- `ORCHESTRATOR_ARCHITECTURE.md` — Complete architecture
- `PHASE_4_PLAN.md` — This file

**Agents (from Phase 1):**
- `src/agents/base_agent.py` — Base classes
- `src/agents/api_agent.py` — API parent
- `src/agents/browser_agent.py` — Browser parent
- `src/agents/greenhouse_agent.py` — Greenhouse impl
- `src/agents/lever_agent.py` — Lever impl
- `src/agents/ashby_agent.py` — Ashby skeleton

---

## Critical Context for Next Session

### Architecture Decisions
1. **Two abstract parents:** APIAgent (Greenhouse, Lever), BrowserAgent (Ashby, LinkedIn)
2. **No auto-fail on unknown fields:** Flag for manual review instead
3. **Deduplication:** MD5 hash of (title + company), apply only to primary platform
4. **Rate limiting:** On 429, pause 10min + move to manual queue (don't auto-retry)
5. **Salary extraction:** Try multiple regex patterns, fallback to inclusion (user filters)
6. **Human-in-the-loop:** User explicitly approves batch before applications sent

### Key Design Principles
- **Never lose applications:** Timeout → manual queue, not fail
- **100% traceability:** Every app linked to user approval or error
- **Graceful degradation:** Partial discovery failure continues with good jobs
- **Conservative defaults:** Unknown salary included, below-floor marked with warning

### Test Coverage (17 tests)
- Slice 1: 8 tests (discovery, salary, digest, approvals, end-to-end)
- Slice 5: 3 tests (deduplication)
- Slice 2: 2 tests (empty discovery)
- Slice 8: 2 tests (rate limiting)
- Slice 9: 1 test (timeout handling)
- Slice 10: 1 test (error recovery)

**All 17 tests passing.** No failures, no regressions.

---

## Git History
Latest commits:
1. Phase 2 COMPLETE: All 10 slices tested and passing (17/17)
2. Add comprehensive orchestrator architecture documentation
3. Phase 2: Slices 5 + 8 - Deduplication + Rate Limiting
4. Phase 3: Backend review fixes (critical issues)
5. Phase 2: Job discovery orchestrator - Slice 1 complete

---

## Recommended Next Session Flow

1. **Start fresh session** with this handoff prompt
2. **Phase 3: Run backend pre-merge review** on all orchestrator modules
3. **Phase 3: Run security auditor review** on critical modules
4. **Phase 3: Fix all findings** (loop until zero findings)
5. **Phase 4: Create acceptance tests** (tests/test_acceptance_orchestrator.py)
6. **Phase 4: Implement orchestrator.py** main loop
7. **Phase 4: Run acceptance suite** (verify end-to-end workflow)
8. **Phase 5: Ship** (create final commit + PR summary)

---

## Success Criteria

**Phase 4 complete when:**
- ✓ Backend + security reviews pass (zero findings)
- ✓ 5+ acceptance tests passing (end-to-end, gates, edge cases)
- ✓ orchestrator.py implemented + tested
- ✓ No regressions from Phase 2 (17 tests still passing)
- ✓ Database integration verified (batch → job → application flow)
- ✓ Error handling validated (rate limits, timeouts, partial failures)

---

## Known Limitations / Deferred

- **Ashby Playwright:** Deferred to Phase 2.2 (skeleton in place)
- **2captcha:** Mock only (real integration Phase 2.3)
- **Gmail OAuth:** Mock client (real auth Phase 2.3)
- **Datasette dashboard:** Not MVP (low priority)
- **Workday:** Phase 2 backlog

---

## Questions for Next Session

If stuck, refer to:
- **Architecture decisions:** ORCHESTRATOR_ARCHITECTURE.md
- **Module details:** Code comments + docstrings
- **Test patterns:** test_orchestrator_slices.py
- **Database schema:** src/database/schema.py
- **Design rationale:** ORCHESTRATOR_CONTEXT.md

---

## Approx. Time for Phase 4

- Backend review fixes: 15 min
- Acceptance tests: 30 min
- orchestrator.py implementation: 45 min
- Integration testing: 30 min
- **Total: ~2 hours**

---

**Status: Phase 2 ✓ complete, Phase 3 in progress, Phase 4 ready to start.**

Good context for handoff. All critical information documented. Fresh session can pick up with full understanding.

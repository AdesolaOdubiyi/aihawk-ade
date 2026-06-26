# Phase 2: Job Discovery & Orchestrator — Context & Design

## Feature Overview

**Human-in-the-loop batch job discovery and approval before auto-application.**

User flow:
1. Claude discovers jobs (Greenhouse, Lever APIs)
2. Claude filters by criteria (salary ≥$40/hr, location flexible, 2027 internships)
3. Claude sends email digest to user (structured markdown)
4. User reviews, approves/rejects jobs
5. User replies "APPROVE" or similar
6. Claude auto-applies to approved jobs only

**Control:** User approves before ANY application sent. Daily reminders if pending.

---

## Design Decisions

### 1. Email Digest Format
- **Structured markdown** (easy human read)
- Include: title, company, link, salary (if found), location
- Example:
  ```markdown
  # Job Discovery Batch (2025-01-15)
  
  ## Job 1: Software Engineer
  - **Company:** TechCorp
  - **Salary:** $50/hr
  - **Location:** Remote
  - **Link:** [Apply](https://greenhouse.io/...)
  
  APPROVE or REJECT this job in your reply.
  ```

### 2. User Approval Format
- **Email reply with "APPROVE" markers**
- User can reply: "APPROVE: Job 1, Job 3, Job 5"
- Or: "REJECT: Job 2, Job 4"
- Or: "APPROVE all"
- Parser extracts job IDs, updates DB

### 3. Batch Timeout & Reminders
- **No auto-apply on timeout** — User must explicitly approve
- **Daily reminders** — "You have 2 pending job batches (15 jobs). Please review."
- **Batch expires after 7 days** (or configurable) — User can still approve later, but marked stale
- **No silent action** — All applications traced to explicit user approval

### 4. Salary Extraction (Try-All)
1. **Regex from description** — Extract "$X/hr" or "$X,XXX/year"
2. **Try alternative formats** — "X per hour", "salary: X", etc.
3. **Fallback:** If salary not found, still include job (user can filter manually)
4. **Floor check:** If salary < $40/hr, mark as "Below threshold" but still include (user override possible)

Rationale: Better to include + let user filter than miss legitimate jobs.

### 5. Job Deduplication (Same Job, Multiple Platforms)
- **Problem:** Same job posted on Greenhouse + Lever = duplicate application
- **Detection:** Match by (company, title, job_id if available) or (company, title, description hash)
- **Resolution:** Apply only to PRIMARY platform
  - Primary = user's preference (e.g., "apply via Greenhouse if on both")
  - Or first discovered (Greenhouse > Lever > Ashby)
- **DB:** Add `is_duplicate_of` field to link duplicates
- **Application:** Apply to one, mark others as "applied via [primary]"

### 6. Ashby Playwright Integration
- **Defer to Phase 2.2** — After MVP discovery + batch approval works
- **Reason:** Validate current architecture before adding browser automation complexity
- **Phase 2.2 scope:** Full Playwright implementation (form parsing, field filling, CAPTCHA)

### 7. CAPTCHA Handling
- **Mock for Phase 2** — `MockCaptchaSolver` returns fake solution
- **Real 2captcha:** Phase 2.3 (after Ashby working)
- **Allows:** Test orchestrator flow without external deps

### 8. Database Schema (New Tables)

#### `job_batches`
```
id, discovered_at, discovery_source (greenhouse/lever/both), 
status (pending/approved/expired), batch_size, user_id, 
created_at, expires_at
```

#### `batch_jobs`
```
id, batch_id, job_id, user_approval_status (approved/rejected/pending),
approved_at, is_duplicate_of (links to primary job_id)
```

#### `job_discoveries`
```
id, platform, job_id, title, company, salary_raw, salary_parsed, 
location, link, discovered_at, batch_id
```

#### `approval_log`
```
id, batch_id, user_email, approval_text, parsed_approvals (JSON),
received_at, processed_at
```

#### Update `applications`
```
Add: batch_id, approved_by_user (boolean), approval_timestamp
```

---

## Success Criteria

✓ Job discovery API calls working (Greenhouse, Lever)  
✓ Salary parsing (regex + fallback)  
✓ Email digest generation (markdown)  
✓ Approval parsing (email reply)  
✓ Deduplication detection + linking  
✓ Orchestrator loop (discover → digest → wait → approve → apply)  
✓ Daily reminders on pending batches  
✓ All applications linked to explicit user approval  
✓ Zero applications without approval  

---

## Test Matrix (10 TDD Slices)

1. **Slice 1 (Happy Path):** Discover 3 jobs, parse salary, generate digest, user approves, apply
2. **Slice 2 (Empty Discovery):** No jobs found, user notified, no batch created
3. **Slice 3 (Salary Parsing):** Extract "$50/hr", "$75,000/year", "salary: $X", regex edge cases
4. **Slice 4 (Salary Below Floor):** Job has $30/hr, marked below threshold, user can still approve
5. **Slice 5 (Deduplication):** Same job on Greenhouse + Lever, apply only once (to Greenhouse)
6. **Slice 6 (Approval Parsing):** User replies "APPROVE: 1,3,5", parse correctly
7. **Slice 7 (Partial Approval):** User approves 3/5 jobs, apply only to 3
8. **Slice 8 (Batch Timeout):** No approval for 7 days, batch expires, reminder sent
9. **Slice 9 (API Timeout):** Discovery API timeout, retry, fail gracefully, queue for manual review
10. **Slice 10 (Rate Limiting):** Discover 50 jobs, hit rate limit 429, pause, resume later

---

## Documentation Plan (MD Files)

As we build Phase 2, create:

- **ORCHESTRATOR_FLOW.md** — State machine (discovery → digest → waiting → approved → applying)
- **SALARY_EXTRACTION.md** — Regex patterns, test cases, fallback strategy
- **DEDUPLICATION_STRATEGY.md** — Detection logic, primary platform rules, manual override
- **EMAIL_DIGEST_TEMPLATE.md** — Markdown example, user reply parsing
- **APPROVAL_PARSING.md** — Regex for email reply, edge cases
- **RATE_LIMITING.md** — 429 handling, pause duration, manual queue logic
- **ORCHESTRATOR_API.md** — `Orchestrator` class, methods, error handling

Goal: New LLM/engineer can pick up mid-Phase-2 without missing context.

---

## Architecture (Phase 2 Additions)

```
src/
├── orchestrator/
│   ├── __init__.py
│   ├── orchestrator.py         (main loop)
│   ├── discovery.py            (Greenhouse, Lever discovery)
│   ├── salary_extractor.py     (regex + fallback)
│   ├── deduplicator.py         (duplicate detection)
│   ├── digest_generator.py     (markdown email)
│   ├── approval_parser.py      (parse user replies)
│   └── rate_limiter.py         (pause on 429)
├── database/
│   └── schema.py               (updated: new 4 tables)
└── [existing agents, email, forms]

tests/
├── test_orchestrator_slices.py (10 slices)
├── test_salary_extraction.py
├── test_deduplication.py
└── test_approval_parsing.py
```

---

## Dependencies (New)

- `email-validator` (validate email parsing)
- `markdown` (generate markdown, optional for now)
- No new major deps; regex built-in

---

## Phase 2 Timeline

- Slices 1-5: 45 min (discovery, filtering, digest, dedup)
- Slices 6-10: 45 min (approval, batch timeout, rate limit, recovery)
- Review loop: 20 min (backend, security)
- Acceptance: 15 min (end-to-end workflow)
- Ship: 5 min (commit, summary)

**Total:** ~2 hours (similar to Phase 1)

---

## Next: Phase 2 TDD
Ready to start Slice 1 (happy path: discover 3 jobs → parse salary → generate digest → user approves → apply).

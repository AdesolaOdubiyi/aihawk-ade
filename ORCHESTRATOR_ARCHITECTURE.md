# Orchestrator Architecture & Design Patterns

## Module Overview

```
orchestrator/
├── discovery.py          (Slice 1: Job discovery from Greenhouse, Lever)
├── salary_extractor.py   (Slice 3-4: Regex salary parsing)
├── digest_generator.py   (Slice 1: Markdown email digest)
├── approval_parser.py    (Slice 6-7: Parse user replies)
├── deduplicator.py       (Slice 5: Detect duplicates across platforms)
├── rate_limiter.py       (Slice 8: Handle 429 rate limits)
└── orchestrator.py       (Slice 5: Main orchestration loop) [TODO]
```

---

## Slice 1: Job Discovery (✓ PASSING)

**What it does:** Fetch jobs from platform APIs (Greenhouse, Lever)

**Key design:**
- Separate functions: `discover_greenhouse()`, `discover_lever()`
- Error handling: Timeout (10s), return empty list on failure
- No retry at discovery stage (user re-runs discovery)

**Example:**
```python
jobs = discover_jobs(platform="greenhouse", board_token="abc123")
# Returns: [JobListing(id, title, company, url, platform), ...]
```

**Critical fix applied:**
- Company extraction: Parse nested `organization.name` field (not title!)

---

## Slice 3-4: Salary Extraction (✓ TESTED)

**What it does:** Extract hourly rate from job descriptions

**Regex patterns (tried in order):**
1. Hourly: `$50/hr`, `$50 per hour`
2. Annual range: `$45K - $55K`, `$45,000 - $55,000`
3. Annual single: `$75,000/year`, `$75K annually`
4. Shorthand: `$50K` (if < 100, assume hourly; else annual)

**Fallback:** If not found, return None (user can filter manually)

**Normalization:**
- Annual → hourly: `salary / 2080` (work hours/year)
- Returns: float (hourly rate) or None

**Floor enforcement:**
```python
meets_floor(salary=50.0, floor=40.0)  # True
meets_floor(salary=None, floor=40.0)  # True (unknown passes)
```

---

## Slice 5: Deduplication (✓ PASSING)

**What it does:** Detect same job posted on multiple platforms

**Algorithm:**
- Hash fingerprint: `MD5((title + company).lower())`
- O(1) duplicate detection
- Tracks: primary_job_id → [duplicate_ids]

**Design choice:**
- Hash-only (no fuzzy matching) — job titles on same platforms are consistent
- If needed later: add RapidFuzz for typo tolerance (0.85 threshold)

**Example:**
```python
dedup = JobDeduplicator()
job1 = JobListing(id="gh-123", title="Engineer", company="A", ...)
job2 = JobListing(id="lv-456", title="Engineer", company="A", ...)

dedup.add_job(job1)  # (id, False) - primary
dedup.add_job(job2)  # (id, True) - duplicate of job1
```

**Resolution:** Apply only to primary platform (Greenhouse > Lever > Ashby)

---

## Slice 6-7: Approval Parsing (✓ TESTED)

**What it does:** Parse user email replies to extract approved job IDs

**Expected formats:**
- `APPROVE: 1, 3, 5` → [1, 3, 5]
- `APPROVE all` → [1, 2, 3, ..., N]
- `REJECT: 2, 4` → rejected = [2, 4]
- Mixed: `APPROVE: 1, 3\nREJECT: 2` → approved=[1,3], rejected=[2]

**Implementation:**
- Regex case-insensitive: `approve:\s*([\d,\s]+)`
- Parse ID list: Split by comma/space, extract digits
- **Validation (added Phase 3):** Check IDs are in range [1, total_jobs]

**Return modes:**
```python
# Simple: return approved IDs
parse_approvals("APPROVE: 1, 3", total_jobs=5)
# → ["1", "3"]

# Full: return approved + rejected + unanswered
parse_approvals("APPROVE: 1, 3", total_jobs=5, return_all=True)
# → {approved: ["1", "3"], rejected: [], unanswered: ["2", "4", "5"]}
```

---

## Slice 8: Rate Limiting (IN PROGRESS)

**What it does:** Handle API 429 responses gracefully

**Handler logic:**
1. **Detect 429:** HTTP status code 429
2. **Extract wait time:** Read `Retry-After` header, default 600s (10 min)
3. **Pause:** Set `paused_until = now + wait_seconds`
4. **Queue manually:** Move application to `manual_review_queue`
5. **Resume:** Check `is_paused()` before next discovery attempt

**Retry backoff (if enabled):**
- Attempt 0: wait 1s
- Attempt 1: wait 2s
- Attempt 2: wait 4s
- Attempt 3: wait 8s
- Attempt 4: wait 16s
- Max attempts: 5 (gives up after 31s total + jitter)

**Jitter:** ±20% random to avoid thundering herd

**Never auto-apply backoff to discovery:** Instead, pause globally and notify user

---

## Slice 1: Digest Generation (✓ TESTED)

**What it does:** Generate markdown email digest of discovered jobs

**Structure:**
```markdown
# Job Discovery Batch

**Generated:** 2025-01-15 14:32
**Batch ID:** batch-xyz
**Total Jobs:** 3

---

## Job 1: Software Engineer

- **Company:** TechCorp
- **Platform:** Greenhouse
- **Salary:** $50.00/hr
- **Link:** [greenhouse.io/...](url)

...

## Action

Reply with your approval:
```
APPROVE: 1, 3, 5
REJECT: 2, 4
```

Or: `APPROVE all` or `REJECT all`

Only approved jobs will be auto-applied.
```

**Design choices:**
- Markdown (easy human scan)
- Include salary if found, mark if below floor (⚠️)
- Clear action instructions
- Job numbers match batch_jobs table indices

---

## Slice 2: Empty Discovery (TODO)

**What it does:** Handle no jobs discovered (edge case)

**Behavior:**
- No batch created
- User notified: "No jobs match your criteria"
- No errors, graceful exit

---

## Slice 9: Timeout Handling (TODO)

**What it does:** Handle API timeouts during discovery

**Timeout strategy:**
- HTTP timeout: 10s (per request)
- No retries at discovery (user re-runs)
- Log and move to manual queue if needed

---

## Slice 10: Error Recovery (TODO)

**What it does:** Recover from partial failures

**Patterns:**
- Discover 50 jobs, 3 failed API calls
- Don't fail entire batch; mark failed ones for manual review
- Continue discovery for others

---

## Integration: Orchestrator Loop (TODO)

**Pseudo-code:**
```python
def run_orchestrator():
    # 1. Discover
    jobs_gh = discover_jobs("greenhouse", board_token=...)
    jobs_lv = discover_jobs("lever", company=...)
    all_jobs = jobs_gh + jobs_lv

    # 2. Deduplicate
    dedup = JobDeduplicator()
    unique_jobs = dedup.filter_non_duplicates(all_jobs)

    # 3. Extract salaries + filter
    jobs_with_salary = []
    for job in unique_jobs:
        salary = extract_salary(job.description)
        if meets_floor(salary, floor=40.0):
            jobs_with_salary.append((job, salary))

    # 4. Generate digest
    digest = generate_digest(
        jobs=[j for j, _ in jobs_with_salary],
        salaries={j.id: s for j, s in jobs_with_salary},
        salary_floor=40.0
    )

    # 5. Send to user
    send_email_digest(user_email, digest)

    # 6. Wait for approval
    # ... (background job polls for reply)

    # 7. Parse approvals
    approvals = parse_approvals(user_reply, total_jobs=len(jobs_with_salary))

    # 8. Apply to approved jobs
    for job in approved_jobs:
        result = apply_agent(job, user_profile)
        # Track result in applications table

    # 9. Track in DB
    # job_batches -> batch_jobs -> applications
```

---

## Database Integration

**Key tables:**
- `job_batches`: One per discovery run
- `batch_jobs`: Jobs in batch + user approval status
- `job_discoveries`: Raw discovered jobs (with salary_hourly, salary_annual)
- `approval_log`: User email replies

**Foreign keys:**
- `batch_jobs.batch_id` → `job_batches.id`
- `batch_jobs.job_id` → `jobs.id`
- `approval_log.batch_id` → `job_batches.id`

**Indexes:**
- `batch_jobs` on `batch_id, user_approval_status` (for approval queries)
- `approval_log` on `batch_id, received_at` (for polling)

---

## Error Handling Philosophy

**Design: Don't lose applications**
- Timeout → manual queue (not skip)
- 429 → pause + manual queue (not retry infinitely)
- Approval parsing error → flag + manual queue
- Unknown salary → include job anyway (user filters)
- Invalid ID in approval → ignore + log warning

**Result: 100% traceability**
Every application linked to explicit user approval or error state.

---

## Testing Strategy

**Per slice:**
- Happy path (what should happen)
- Empty state (no data)
- Edge cases (boundary conditions)
- Error conditions (timeouts, invalid input)

**Total slices: 10**
- Slice 1: Discovery ✓
- Slice 2: Empty discovery [TODO]
- Slice 3-4: Salary extraction ✓
- Slice 5: Deduplication ✓
- Slice 6-7: Approval parsing ✓
- Slice 8: Rate limiting [IN PROGRESS]
- Slice 9: Timeout handling [TODO]
- Slice 10: Error recovery [TODO]

---

## Performance Notes

**At scale (1000+ jobs/day):**
- Deduplication: O(n) hashing (no slowdown)
- Salary extraction: O(n) regex (acceptable)
- Email digest: O(n) markdown generation (< 1s)
- Approval parsing: O(1) regex extraction (< 10ms)

**Memory:** < 10MB for 1000-job batch

**Bottleneck:** API discovery (rate limits, timeouts) — not orchestrator logic


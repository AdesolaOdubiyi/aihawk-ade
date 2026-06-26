# Job Application Automation Tool — Context & Design

## Feature Overview

**Objective:** Automate 50%+ of job applications (targeting 100–150 submitted out of 200–300 total) with zero account bans and zero ToS violations on targeted platforms.

**MVP Platforms:**
- Greenhouse (API submission)
- Lever (API submission, endpoint validity test first)
- Ashby (Playwright submission with stealth)
- LinkedIn (discovery only, existing AIHawk coverage)

**Success Criteria:**
- ≥100 applications submitted automatically
- 0 account bans
- All failures logged with context for manual completion
- Email triage correctly classifies rejection vs interview vs action-needed

---

## Architecture Decisions

### 1. Two Abstract Parent Classes

```
Agent (ABC)
├── APIAgent (abstract)
│   ├── GreenhouseAgent
│   └── LeverAgent
└── BrowserAgent (abstract)
    ├── AshbyAgent
    └── LinkedInAgent (existing)
```

**Rationale:** Separate API-driven from browser-driven platforms. Reduces conditional logic, simplifies testing, allows platform-specific optimizations.

**Common interface:**
- `submit_application(job: JobListing, profile: CandidateProfile) → ApplicationResult`

**API-specific:**
- `fetch_form_definition(job_id: str) → FormDefinition`

**Browser-specific:**
- `parse_form() → FormDefinition`
- `handle_email_verification(timeout_seconds: int) → bool`

**Implementation detail:** New classes separate from `AIHawkEasyApplier`. Not extending existing LinkedIn agent; allows clean slate design for multi-platform consistency.

---

### 2. Unknown Required Field Policy

**Default behavior:** Treat identically to freeform questions.
1. Flag for manual review (do not fail, do not skip)
2. Log field name, field type, application URL
3. Add to `manual_review_queue` table
4. Continue filling remaining fields
5. Submit what can be submitted; alert user of manual flag

**Rationale:** Incomplete + accurate beats complete + mismatched. Better to require one manual field than guess and create a bad application.

---

### 3. Browser Automation: Playwright

**Decision:** Use Playwright (not Selenium) for Ashby + future platforms.

**Why Playwright over Selenium:**
- 10x throughput (4–8 concurrent contexts vs 1–2 browsers)
- Auto-waiting eliminates timing flakiness (92% vs 72% stability)
- Better debugging (visual trace replay vs stack traces)
- Stealth anti-detection via plugin (modern + maintained)
- Async/await reduces boilerplate

**Anti-detection strategy:**
- playwright-stealth plugin for JavaScript fingerprints
- User-agent rotation per session
- Timezone + geolocation randomization
- Human-like delays (200–500ms between field interactions)
- 24–48h spacing between applications (behavioral detection)
- Residential proxy essential for enterprise job boards

---

### 4. Form Filling Strategy

**7-level detection hierarchy:**
1. HTML5 type (95% confidence)
2. ARIA attributes (90%)
3. CSS classes (70%)
4. Placeholders (60%)
5. Label fuzzy matching (50%)
6. Token overlap (30%)
7. Manual review (< 30%)

**Decision thresholds:**
- Confidence ≥ 0.80: Auto-fill
- 0.65–0.80: Conditional (optional fields only)
- < 0.65: Skip, flag for manual review

**Required field detection** (6 signals):
- HTML5 `required` attribute
- ARIA `aria-required="true"`
- Asterisk in label
- CSS class "required"/"mandatory"
- Error state on parent
- Skip button presence

**Logging:** Every field decision logged to JSONL + CSV export for continuous improvement.

---

### 5. Email Triage Classification

**No LLM.** Regex + heuristic scoring (85–95% accuracy).

**Rejection patterns** (score ≥ 7.5):
- Subject: "unfortunately", "regret", "not moving forward", "at this time"
- Body: "decided to move forward with another" (+8), "appreciated but" (+5)

**Interview patterns** (score ≥ 7.0):
- Scheduling links (Calendly, Doodle) = +10
- "Phone screen", "video call" = +7
- Specific dates/times = +8

**Action-required patterns** (score ≥ 7.0):
- "Background check" + deadline = +8
- "Submit by [date]" = +10
- Assessment + "within X days" = +8

**Confidence thresholds:**
- ≥ 0.75: Auto-reject
- ≥ 0.70: Auto-interview
- ≥ 0.65: Auto-action-required
- 0.50–0.75: Manual review
- < 0.50: Flag as unknown

**False positive avoidance:** Deceptive rejections, phishing, soft rejections, marketing emails.

---

### 6. CAPTCHA Handling

**Service:** 2captcha API (new dependency)

**Detection:** reCAPTCHA v2 (95%), Cloudflare Turnstile

**Flow:**
1. Detect CAPTCHA → submit to 2captcha
2. Poll with exponential backoff (10s → 5s intervals)
3. Timeout: 120s max (2captcha SLA ~30–60s)
4. Max 3 attempts per CAPTCHA (exponential backoff: 1s, 2s, 4s)

**Circuit breaker:**
- Open after 3 consecutive failures
- Wait 5–10 min before reset
- Fallback: Route to Anti-Captcha if primary fails

**Fallback on failure:** Add to manual review queue, notify user (don't retry infinitely)

**Cost:** ~$0.60–0.90/month for 50 apps/day (1 CAPTCHA per 2–3 apps)

---

### 7. Data Storage — SQLite

**Location:** `data_folder/jobs.sqlite` (follows existing patterns)

**Core tables:**

```sql
jobs (
  id, title, company, platform, url, discovered_at, status
)
-- status: pending | submitted | failed | manual_required

applications (
  id, job_id, submitted_at, result, error_log, screenshot_path,
  current_status, needs_review, review_priority, confidence_score
)

email_triage (
  id, received_at, sender, subject, classification, confidence_score,
  raw_snippet, review_status
)
-- classification: rejection | interview | action_required | noise

manual_review_queue (
  id, job_id, question_text, field_name, application_url,
  flagged_at, category, priority
)
-- category: unknown_field | freeform_question | captcha_failed | email_flagged

status_history (
  id, application_id, old_status, new_status, changed_at,
  changed_by, is_manual, automation_type
)
-- immutable audit trail
```

**Visualization:** Datasette (`datasette data_folder/jobs.sqlite`) for MVP (no custom dashboard)

---

### 8. Error Handling

**Default policy:** Retry once after 30-second delay → skip and log.

**On failure, log:**
- Application URL
- Platform
- Error message/stack trace
- Full-page screenshot
- Fields successfully filled before failure
- Timestamp

**CAPTCHA:** See Section 6 (2captcha integration)

**Rate limit / bot detection:** Pause run for 10 minutes, move application to manual review queue, do not retry immediately.

---

### 9. Implementation Gates

**Gate 1 — Before any Lever code:** Manually POST to `jobs.lever.co/{company}/{id}/apply` against 2–3 real postings. Confirm no CSRF or session requirement. If gated → move to BrowserAgent tier.

**Gate 2 — Before scaling:** Phase 1 smoke test must pass 5/5 (2 Greenhouse, 2 Lever, 1 Ashby). Success = application submitted + confirmation email received + correct SQLite entry.

**Gate 3 — Before full runs:** Phase 2 regression baseline: 20 applications, ≤20% failure rate. Failures must not cluster on a single platform.

---

### 10. Dependencies (New)

- **Playwright** (v1.50+): Browser automation with stealth
- **2captcha** (unofficial SDK or direct HTTP): CAPTCHA solving
- **google-auth** + **google-auth-oauthlib**: Gmail OAuth (for email triage)
- Existing: httpx, PyYAML, pytest, loguru, selenium (keep for backward compat)

---

## Phase 2: TDD Vertical Slices

### Test Matrix

**Slice 1 (Happy path):** Greenhouse API submission succeeds
- Test: POST to Greenhouse API with valid form data
- Expect: 200, application ID returned, SQLite entry created

**Slice 2 (Unknown field):** Required field not in YAML map
- Test: Submit form with unmapped required field
- Expect: Field flagged, logged to manual_review_queue, other fields submitted
- Verify: No submission failure, manual_review_queue populated

**Slice 3 (Invalid input):** Bad email format
- Test: Submit form with invalid email (e.g., "not-an-email")
- Expect: Field validation error caught, flagged for manual review, application skipped
- Verify: Error logged, manual queue populated

**Slice 4 (Timeout handling):** API request timeout
- Test: Mock Greenhouse API to timeout after 5s
- Expect: Retry once after 30s, then fail and log
- Verify: Retry count = 1, error logged with context

**Slice 5 (Empty state):** No jobs in queue
- Test: Run application with empty job list
- Expect: Graceful exit, no errors, log "No jobs to process"
- Verify: SQLite unchanged, no hanging processes

**Slice 6 (Partial state):** One job succeeds, one fails
- Test: Queue 2 jobs; first succeeds, second has invalid form
- Expect: First application submitted, second flagged
- Verify: SQLite shows 1 success + 1 manual_required, execution continues

**Slice 7 (CAPTCHA detected):** reCAPTCHA v2 on Ashby form
- Test: Ashby form with reCAPTCHA, mock 2captcha solver
- Expect: CAPTCHA detected → submitted to 2captcha → token injected → form submitted
- Verify: Successful submission after CAPTCHA solve

**Slice 8 (CAPTCHA solve timeout):** 2captcha takes > 120s
- Test: Mock 2captcha to timeout
- Expect: Solve fails, retry once, then skip and flag for manual
- Verify: Manual review queue populated, application skipped

**Slice 9 (Email triage rejection):** Reject email received
- Test: Mock Gmail API, receive email with rejection patterns
- Expect: Classified as REJECTION, confidence ≥ 0.75
- Verify: email_triage table shows rejection + confidence

**Slice 10 (Email triage ambiguous):** Ambiguous email (low confidence)
- Test: Email that matches multiple patterns with low confidence
- Expect: Classified as NOISE or flagged for manual review
- Verify: email_triage shows low confidence, review_status = unreviewed

**Slice 11 (Rate limit hit):** 429 Too Many Requests from Greenhouse
- Test: Mock Greenhouse API to return 429
- Expect: Pause run for 10 min, move application to manual_review_queue
- Verify: Application not retried, manual queue populated, timer set

**Slice 12 (API vs Browser consistency):** Same job via both API and Browser
- Test: Submit same job via GreenhouseAgent (API) and AshbyAgent (Browser)
- Expect: Both succeed, both create SQLite entries, same job_id
- Verify: Two applications with same job_id, different platforms

---

## File Structure (Updated)

```
C:\Users\odubi\dev\aihawk-ade\
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py          (ABC)
│   │   ├── api_agent.py           (APIAgent ABC)
│   │   ├── browser_agent.py       (BrowserAgent ABC)
│   │   ├── greenhouse_agent.py    (GreenhouseAgent)
│   │   ├── lever_agent.py         (LeverAgent)
│   │   ├── ashby_agent.py         (AshbyAgent)
│   │   └── linkedin_agent.py      (existing, refactored)
│   ├── database/
│   │   ├── __init__.py
│   │   ├── schema.py              (SQLite DDL)
│   │   └── models.py              (ORM / dataclasses)
│   ├── email/
│   │   ├── __init__.py
│   │   ├── gmail_client.py        (Gmail OAuth + fetch)
│   │   └── classifier.py          (regex-based classification)
│   ├── forms/
│   │   ├── __init__.py
│   │   ├── field_matcher.py       (7-level detection + confidence scoring)
│   │   └── field_mapping.py       (YAML config loader)
│   ├── captcha/
│   │   ├── __init__.py
│   │   ├── detector.py            (CAPTCHA detection)
│   │   └── solver.py              (2captcha integration)
│   ├── orchestrator.py            (main execution loop)
│   ├── config.py                  (app config)
│   └── utils.py                   (existing utilities)
├── data_folder/
│   ├── jobs.sqlite                (SQLite database)
│   ├── field_mapping.yaml         (platform field variants)
│   ├── logs/                      (application logs)
│   └── screenshots/               (failure screenshots)
├── tests/
│   ├── test_greenhouse_agent.py
│   ├── test_lever_agent.py
│   ├── test_ashby_agent.py
│   ├── test_form_matching.py
│   ├── test_email_classifier.py
│   ├── test_captcha_detection.py
│   └── conftest.py                (pytest fixtures)
├── requirements.txt               (updated with new deps)
├── CONTEXT.md                     (this file)
└── README.md
```

---

## Success Metrics for Phase 2

✅ All 12 TDD slices green
✅ SQLite schema migrations tested
✅ Email classifier regex patterns validated
✅ Playwright + stealth configured + tested
✅ 2captcha integration mocked + tested
✅ No regressions in existing LinkedIn agent
✅ Coverage report: ≥ 85% for new modules

---

## Phase 3 & Beyond

- Backend pre-merge review (security, error handling, API contracts)
- Security auditor review (OWASP, secrets, data flow)
- Acceptance testing: Gate 1, Gate 2, Gate 3 (implementation gates)
- Ship: PR + commit


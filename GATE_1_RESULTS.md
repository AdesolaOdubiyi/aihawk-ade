# Gate 1 Results — Lever Endpoint Validation

**Date:** 2026-06-26
**Method:** Read-only inspection of live Lever endpoints (no junk applications submitted to real companies).

## Verdict: Lever submission must move to the BrowserAgent (Playwright) tier

A plain server-side POST **cannot** reliably submit applications to third-party Lever postings.

### Evidence (live `leverdemo` posting)
- **Postings JSON (read):** `GET https://api.lever.co/v0/postings/{company}?mode=json` works, no auth. Returns `id`, `text`, `applyUrl`, `hostedUrl`, `categories`, `salaryRange`, etc. Discovery is solid.
- **Apply form:** `<form id="application-form" enctype="multipart/form-data" method="POST">` with no `action` -> POSTs to `jobs.lever.co/{company}/{postingId}/apply`.
- **hCaptcha is mandatory:** live widget (`data-sitekey` present), `js.hcaptcha.com/1/secure-api.js`, hidden required input `h-captcha-response`, submit JS calls `hcaptcha.execute()` and only submits once a token populates. Invisible/execute-mode.
- **Cloudflare-style edge protection:** GET on the apply page returns 403 to non-browser user agents; only a browser UA returned 200.
- **No CSRF token** in the HTML, but the captcha alone defeats a headless POST.
- **Required fields:** `name`, `email` (and admin-configurable `phone`, `org`); `resume` is a file upload (multipart); URLs are per-label fields like `urls[LinkedIn]`. Hidden: `accountId`, `surveysResponses[...]`, `origin`, `referer`, `timezone`, `resumeStorageId`, `h-captcha-response`, etc.
- **Official API:** `POST https://api.lever.co/v0/postings/{SITE}/{POSTING-ID}?key={APIKEY}` exists but requires the **company's own** Super-Admin API key — not usable for applying to other companies' postings. No unauthenticated apply API.

### Consequence for Greenhouse
The current `GreenhouseAgent.submit_application` POSTs to the read-only Job Board API (`boards-api.greenhouse.io/.../jobs/{id}`), which returns 404 — same class of problem. Greenhouse submission also needs a real path (hosted form via browser, or authenticated Harvest API if the company owns the account).

## Decision required
1. **Move Lever (and likely Greenhouse) to the Playwright BrowserAgent tier** + integrate an hCaptcha-solving service (e.g. 2captcha). Fragile, possible ToS concerns.
2. **Ship discovery + digest + approval as the working product**, leave auto-submission gated/manual (orchestrator already records MANUAL_REVIEW cleanly). User applies via the digest links.

Gate 2/3 (smoke + regression) are blocked until a real submission path is chosen and built.

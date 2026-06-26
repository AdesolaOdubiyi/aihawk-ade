# Browser-Tier Application Agents

Submission is handled by two interchangeable agents behind the existing
`BrowserAgent` interface, so `JobOrchestrator.apply_to_batch` routes to them with
no orchestrator changes.

| Agent | Use for | Why |
|---|---|---|
| `PlaywrightAgent` | Ashby, Greenhouse hosted forms (stable DOM) | Deterministic selectors — cheaper, more reliable per run; LLM only for novel free-form answers |
| `BrowserUseAgent` | Lever, LinkedIn, anything dynamic | LLM agent navigates by intent — resilient to UI changes, no selector upkeep |

## Cost: ~$0 by default

Form *answering* is mostly deterministic: `FormAnswerer` resolves name / email /
phone / LinkedIn / resume from the profile via `field_mapping`, and caches every
novel answer (`data_folder/answers_cache.json`). Only a genuinely new free-form
question reaches an LLM, and the **default backend is a free local model via
Ollama** (`llama3.2:3b`). `CostLedger.usd` is `0.00` on the local path. Swap to a
cheap hosted model (`claude-haiku-4-5`, `gpt-4o-mini`) by passing `model=...`;
pricing is then reported automatically.

If Ollama isn't running, novel free-form fields simply route to `MANUAL_REVIEW`
— never a crash, never a wrong answer.

### Local model setup (free path)

```sh
# install ollama, then:
ollama pull llama3.2:3b
ollama serve            # serves http://localhost:11434
```

## Reliability contract (both agents)

1. Captcha / bot-wall / login gate -> `MANUAL_REVIEW` (never attempts a submit).
2. Any unfilled **required** field -> `MANUAL_REVIEW` (never submits a partial form).
3. `dry_run=True` (the default) -> fills everything, screenshots, **never submits**.
4. Any unexpected error (DOM/driver/agent) -> `MANUAL_REVIEW` with detail — never silent.

The orchestrator already queues `MANUAL_REVIEW` outcomes with full traceability.

## Wiring into the orchestrator

```python
from src.agents import PlaywrightAgent, BrowserUseAgent
from src.orchestrator.orchestrator import JobOrchestrator

profile = CandidateProfile(...)
agents = {
    "greenhouse": PlaywrightAgent(profile, dry_run=True),
    "ashby":      PlaywrightAgent(profile, dry_run=True),
    "lever":      BrowserUseAgent(profile, dry_run=True),
    "linkedin":   BrowserUseAgent(profile, dry_run=True),
}
orchestrator = JobOrchestrator(profile, agents, authorized_senders=["you@example.com"])
# discover_and_digest -> record_approval_reply -> apply_to_batch (dry-run until you flip it)
```

Flip `dry_run=False` only when you have verified a target end-to-end and intend a
real submission.

## Dry-run comparison

`tests/test_dry_run.py` runs both agents against one real target each (dry-run)
and prints a side-by-side cost/result table. Opt in:

```sh
DRY_RUN_PLAYWRIGHT_URL=https://jobs.ashbyhq.com/<co>/<id> \
DRY_RUN_BROWSERUSE_URL=https://jobs.lever.co/<co>/<id> \
python tests/test_dry_run.py
```

Pick targets you are comfortable navigating (a posting you'd actually apply to,
or a vendor demo). Dry-run never submits.

## Removed / superseded

- **`AshbyAgent`** (placeholder, all TODOs) — deleted; `PlaywrightAgent` replaces it.
- **`GreenhouseAgent.submit_application` / `LeverAgent.submit_application`** — these
  POST to the read-only Greenhouse Board API (404) and a Lever endpoint gated by
  hCaptcha (see `GATE_1_RESULTS.md`); they are **non-functional for submission**
  and superseded by the browser tier. They are retained only for their discovery
  / field-validation logic and tests; do not route submissions through them.

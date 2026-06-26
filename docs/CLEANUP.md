# Repo Cleanup Plan — legacy AIHawk vs. the current system

This repo began as a fork of **AIHawk (Auto_Jobs_Applier_AIHawk)**, a ~2-year-old
Selenium bot that automated **LinkedIn Easy Apply**. The current system is a
different architecture: API-based **discovery** + an **orchestrator** with
human-in-the-loop approval + a **browser tier** (`PlaywrightAgent`,
`BrowserUseAgent`) for submission. The legacy LinkedIn-Selenium code is fully
superseded and **not imported by any current module** (verified by grep).

This doc is the determination of what to keep, remove, or deprecate so future
engineers / Claude sessions aren't misled by dead code.

## KEEP — the current system

| Area | Files |
|---|---|
| Orchestrator | `src/orchestrator/*` (discovery, salary_extractor, digest_generator, approval_parser, deduplicator, rate_limiter, orchestrator) |
| Agents (active) | `src/agents/{base_agent, browser_agent, playwright_agent, playwright_filler, browser_use_agent, browser_use_runner, browser_support, profile_loader}.py` |
| Database | `src/database/{schema,__init__}.py` |
| Email triage | `src/email/{gmail_client, classifier, __init__}.py` |
| Forms | `src/forms/field_mapping.py` |
| Config | `data_folder/{field_mapping.yaml, candidate_profile.example.yaml}` |
| Tests | `test_orchestrator_slices, test_acceptance_orchestrator, test_acceptance_gates, test_browser_agents, test_playwright_local, test_profile, test_dry_run, conftest` |

## REMOVE — legacy AIHawk LinkedIn-Selenium (self-contained, superseded)

Nothing in the current system imports these; their tests already fail to import
(missing `selenium` / `inputimeout` / `reportlab`), so they are dead today.

| File | Why remove |
|---|---|
| `main.py` | Legacy entrypoint that wires the Selenium LinkedIn flow. The current entrypoint is the orchestrator. |
| `src/aihawk_authenticator.py` | LinkedIn Selenium login (manual checkpoint waiting). |
| `src/aihawk_bot_facade.py` | Facade over the Selenium bot. |
| `src/aihawk_easy_applier.py` | 850-line LinkedIn Easy Apply Selenium driver. Superseded by `BrowserUseAgent`. |
| `src/aihawk_job_manager.py` | LinkedIn search/iteration via Selenium. Superseded by `discovery.py`. |
| `src/job.py`, `src/job_application_profile.py` | Legacy data models. Superseded by `JobListing` / `CandidateProfile`. |
| `src/strings.py`, `src/utils.py` | LinkedIn prompt strings / Chrome-driver utilities. |
| `src/llm/llm_manager.py` (+ `src/llm/__init__.py`) | Multi-provider langchain LLM used only by `easy_applier`. The current answerer uses local Ollama via httpx in `browser_support.py`. |
| `tests/test_aihawk_*.py` (4), `tests/test_job_application_profile.py`, `tests/test_utils.py` | Tests for the removed modules; currently erroring on import. |
| `data_folder/{plain_text_resume.yaml, config.yaml}` | Legacy profile config; superseded by `candidate_profile.yaml`. (`secrets.yaml` is gitignored.) |

**requirements.txt** — drop once the above are gone: `selenium`, `webdriver-manager`,
`inputimeout`, `reportlab`, `lib_resume_builder_AIHawk`, `openai`, and the
`langchain*` stack **except** `langchain-ollama` (kept as a fallback model
backend for `browser_use_runner`). Keep `httpx`, `PyYAML`, `loguru`, `Levenshtein`
(if still used), `pytest*`, `playwright*`, `browser-use`, `google-*` (Gmail).

## DEPRECATE — keep for now, retire later

| File | Status |
|---|---|
| `src/agents/{api_agent, greenhouse_agent, lever_agent}.py` | Their **submission** paths are non-functional/superseded by the browser tier (see GATE_1_RESULTS.md). Discovery lives in `orchestrator/discovery.py`. Retained only for `greenhouse_agent`'s field-validation logic and `test_greenhouse_agent.py`. Remove when that test is migrated or dropped. Do **not** route submissions through them. |

## Repo hygiene

- **Stale git worktree:** `.claude/worktrees/agent-a7987c94ba408e972/` is a full
  duplicate of the repo from an old agent run — it pollutes greps and search.
  Remove with `git worktree remove .claude/worktrees/agent-a7987c94ba408e972`
  (or `git worktree prune` if already detached).
- **Pre-existing test failures:** the 3 failures in `test_greenhouse_agent.py`
  (fixtures called directly → live network 404s) predate all current work;
  fix or remove when touching that file.

## Suggested execution order (each step keeps tests green)

1. Remove the legacy `tests/test_aihawk_*`, `test_utils.py`,
   `test_job_application_profile.py` (they only error). Run the suite.
2. Remove the legacy `src/` modules + `main.py`. Run the suite.
3. Trim `requirements.txt`. Re-run the suite in a clean venv.
4. Remove the stale worktree.
5. (Later) Retire the API submission agents and their test once `greenhouse_agent`
   field-validation logic is either ported or no longer needed.

> Everything here is committed in git history, so each removal is reversible.

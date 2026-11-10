# Jira Release Evidence Agent

A Jira Cloud importer and bounded Gemini tool-calling agent. It checks the mandatory requirements linked from a release manifest, investigates ticket comments and dependencies, and produces a release report with exact Jira comment references. A ticket's workflow status cannot approve a requirement.

The application uses Python **3.12+**, with **no third-party runtime dependencies**. The tested interpreter is pinned in `.python-version`. Optional test dependencies are pinned in `requirements-dev.txt`.

The actual Jira/Gemini run is included: [release report](submission/report.md), [structured decisions and metrics](submission/report.json), [investigation trace](submission/trace.jsonl), and [validation results](submission/README.md). It completed in **104.813 seconds**, with **8 model calls**, **22 tool calls**, and **60,315 reported tokens**. All 12 decisions matched the independent regression check: **4 PASS, 4 FAIL, 4 INSUFFICIENT_EVIDENCE; overall BLOCKED**. All **42 tests** passed in a clean virtual environment without runtime packages.

## Setup

Create a dedicated Jira Cloud project (the supplied configuration uses `TYN`). The importing account needs Browse Projects, Create Issues, Edit Issues, Add Comments and Link Issues. The assessment only reads Jira. Enable the `Task` issue type or set `JIRA_ISSUE_TYPE` to an available type. Required custom fields must have defaults.

From the repository root:

```powershell
python -m venv .venv
Copy-Item .env.example .env
```

Edit `.env` locally with your actual Jira site URL, Jira login email, Jira API token, Gemini key and project. Never commit that file. Use a model supporting Gemini `generateContent` function calling; the actual run's model is recorded in its report. Model availability depends on the account; HTTP 404 can indicate a retired or unavailable model. Restart the application after changing configuration.

There is no runtime `pip install` step. Commands below work with `python` or `.\.venv\Scripts\python.exe`.

## Import and verify

```powershell
python -m importer.jira_importer --dataset inputs/dataset.json --dry-run
python -m importer.jira_importer --dataset inputs/dataset.json --project TYN --workers 8
python -m importer.jira_importer --dataset inputs/dataset.json --project TYN --verify
```

The supplied dataset contains 400 tickets, 2,059 comments and 76 directed source relationships. Every issue receives the **dataset's own `dataset_label`**, `tyn-release-assessment-v2`. The importer preserves source IDs in summaries and descriptions, exact original descriptions, source-recorded statuses, relationship IDs, and every comment (including identical repeated events). Generic native Jira `Relates` links make relationships navigable; the description preserves source direction.

Scenario actor names, roles and event timestamps remain in the comment bodies. Native Jira authors and timestamps belong to the importer. Original workflow statuses are descriptive metadata; the importer does not force workflow transitions.

Reruns discover existing issues in the exact Jira project/label scope. No local database can accidentally point at another site. Comment multisets preserve duplicate occurrences while preventing duplicates on a rerun. Existing source descriptions can be repaired. Conflicting duplicate source IDs cause an error. `import_summary.json` records counts, mappings, input hash, elapsed time and failures. Exit code 2 indicates an incomplete import. Reads retry bounded 429/5xx errors; writes are not automatically retried after ambiguous failures. Fix the problem and rerun.

Import uses at most eight workers across independent tickets. Comments within each ticket remain sequential. `--workers 1` is available for sites with tighter limits. Run only one importer against a given project/label at a time. `--verify` performs a read-only exact-text, comment-multiset and relationship audit.

## Run the assessment

```powershell
python -m agent.graph --project TYN --dataset-label tyn-release-assessment-v2 --release R2.4
```

The CLI accepts the three required inputs. The manifest retrieved from Jira determines the commit, service, environment, deployed prompt and mandatory requirements. The assessment code never opens `inputs/dataset.json`. No external URL fetcher, filesystem tool or other evidence source is exposed to the model.

Every run writes:

```text
reports/<UTC timestamp>-<run ID>/
  report.md       # Human-readable decisions, explanations, follow-up and Jira references
  report.json     # Structured results, execution status and measured usage
  trace.jsonl     # Tool names, arguments, full results, model actions, errors and decisions
```

The model selects `get_evidence_bundle` for up to three requirement roots, receiving their complete comments and recursively linked dependencies, then submits `submit_decisions`. It can also use `get_record` and `search_issues` for further investigation. Evidence is not preloaded into the initial model context. With `--batch-size 1`, it uses individual reads and `submit_decision`. A record read includes **all comment pages** and forward source links. The controller scopes every Jira read, requires recursive linked-record inspection, validates citations against exact retrieved comments, validates decision enums, and computes the overall status itself. Model output cannot independently claim overall readiness.

Each group of at most three requirements has an isolated conversation, reducing calls to fit small provider quotas. Defaults: 14 model turns and 36 tool actions per group, 240,000 context characters per group, 150,000 characters per record, 30 records / 180,000 characters per bundle, 30-second Jira requests, 90-second model requests, and a 1,200-second overall investigation budget. Gemini uses LOW thinking and temperature 1. Exceeding a limit never silently discards evidence or approves a requirement. Use `--timeout` to change the wall-clock budget and `--batch-size 1` for individual investigations. The controller records tool/model failures and assigns incomplete groups `INSUFFICIENT_EVIDENCE`. Failed manifest discovery produces a failed-run artifact with no invented requirement decisions. Partial or failed execution is explicitly distinguished from an evidence-based release decision.

`GEMINI_MIN_INTERVAL_SECONDS` defaults to 5 to pace model requests for account rate limits. Increase it if your account has a lower request allowance. The transport additionally retries 429/5xx responses within its bounded retry policy.

| Requirement evidence | Decision |
|---|---|
| Affirmative, applicable proof | PASS |
| Applicable demonstrated failure | FAIL |
| Missing, inapplicable or genuinely inconclusive evidence | INSUFFICIENT_EVIDENCE |

Any mandatory FAIL → **BLOCKED**. Otherwise any insufficient requirement → **NEEDS_REVIEW**. All mandatory requirements PASS → **READY**. An empty/incomplete investigation cannot produce READY.

## Local dashboard

```powershell
python app.py
```

Open **http://127.0.0.1:8000**. Enter the project, dataset label and release. Validate/import the source records, run an investigation, inspect decisions and download the Markdown report, JSON and trace. Operations run in background threads; a state endpoint reports progress. The server binds to loopback, accepts same-origin requests, and never exposes configured secrets. It is a local development application, not a hosted multi-user service. Both Windows launchers start this same application.

For hosted access, [Render deployment instructions](docs/RENDER.md) and `render.yaml` configure the external host/port and public access to reports, Jira imports and live assessments. There is no username/password prompt. Credentials remain server-side. The committed actual report remains available after a fresh deployment; newly generated report files on the free plan are ephemeral. No paid hosting resources are configured.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Health |
| `GET /api/config` | Non-secret defaults and credential-presence flags |
| `POST /api/import/dry-run` | Source validation, no Jira writes |
| `POST /api/import/start` | Start repeatable import; accepts `project` |
| `POST /api/assessment/run` | Start assessment; accepts `project`, `dataset_label`, `release` |
| `GET /api/status` | Operation state and final result |
| `GET /api/report/latest` | Latest Markdown report |
| `GET /api/report/json` | Latest structured report |
| `GET /api/report/trace` | Latest investigation trace |

The import's label always comes from the supplied dataset, irrespective of the assessment label control.

## Test and package

Standard-library integration and unit tests:

```powershell
python -m unittest discover -v
```

Alternatively, install the pinned optional development dependencies and run all tests with pytest:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The in-memory Jira REST double verifies full dataset fidelity, exact duplicate-comment preservation, pagination, no writes on a rerun, scope guards, recursive inspection, fabricated-citation rejection, model/tool limits, API routes, same-origin checks and transport failures. Scripted models test orchestration only; they are never presented as actual model assessments. Tests do not call live services or require keys.

The independent regression evaluator is **not imported by the agent** and never supplies its expected decisions to the model:

```powershell
python scripts/evaluate_report.py submission/report.json
python scripts/package_submission.py
python scripts/smoke_package.py
```

The packager creates `jira-release-evidence-agent.zip` from an explicit source/artifact allowlist, excludes `.env`, environments, caches and local state, and scans for the configured Jira and Gemini key values. `submission/` contains the actual generated report, trace, execution measurements and validation results when a live run has completed. See [design and limitations](docs/DESIGN.md) for architecture and AI-assistance disclosure.

## Troubleshooting

- **401 / 403:** check the token, login email and project permissions; never put keys in issue text.
- **404:** verify the project/site; for Gemini verify model availability for your account.
- **400 on Jira create:** check issue type, required fields and Jira project configuration.
- **429 / 5xx:** read requests retry at most three attempts with capped waits. Import writes report failures for a safe rerun.
- **Network/model timeout:** inspect the trace and execution status. No offline mock is substituted for a real run.
- **Missing native links/source metadata:** complete or rerun the current importer before assessing.
- **Search pagination cap:** narrow the query; the agent never silently treats truncated results as complete.

The local dataset is used only for importing, import verification and offline tests. Software documentation consulted during implementation is not release evidence; production assessment tools read Jira exclusively.

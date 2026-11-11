# Production inputs and expected outputs

Base URL: https://yellow-release-evidence.onrender.com

## API checks

| Input | Expected output |
|---|---|
| `GET /api/health` | HTTP 200; `{"status":"ok"}` |
| `GET /api/config` | HTTP 200; `model: "openai/gpt-oss-120b"`, `jira_configured: true`, `model_configured: true`; no API keys |
| `POST /api/import/dry-run` with JSON `{}` | HTTP 200; `success: true`, `records: 400`, `comments: 2059`, `relationships: 76` |
| `POST /api/assessment/run` with the JSON below, while idle | HTTP 202; `{"started":true,"operation":"assessment"}` |
| Repeat the assessment request while a job is running | HTTP 409; `{"error":"An operation is already running"}` |
| `GET /api/status` while assessment runs | HTTP 200; `operation: "assessment"`, `status: "running"` |
| `GET /api/status` after successful completion | HTTP 200; `status: "completed"`; result has `execution_status: "COMPLETED"` |
| `GET /api/report/json` after that run | HTTP 200; fresh run ID, `metrics.model: "openai/gpt-oss-120b"`, 12 requirement decisions; expected decisions below |
| `GET /api/report/latest` after that run | HTTP 200; Markdown report with explanations, exact Jira comment citations and follow-up |
| `GET /api/report/trace` after that run | HTTP 200; JSONL tool/model events from the fresh run |
| `POST /api/assessment/run` with JSON `{"release":""}` | HTTP 400; `{"error":"Invalid release"}` |
| `POST /api/assessment/run` with JSON `{"project":"INVALID!"}` | HTTP 400; `{"error":"Invalid Jira project key"}` |
| `POST /api/assessment/run` with JSON `{"release":"NO-SUCH-RELEASE"}`, while idle | Initially HTTP 202; final `execution_status: "FAILED"`, no requirements, `overall_decision: "NEEDS_REVIEW"`; manifest-discovery error |
| POST to an operation endpoint with `Content-Type: text/plain` | HTTP 415; `{"error":"Use application/json"}` |
| POST to an operation endpoint with `Origin: https://untrusted.example` | HTTP 403; `{"error":"Untrusted host or origin"}` |

Assessment request (`Content-Type: application/json`):

```json
{
  "project": "TYN",
  "dataset_label": "tyn-release-assessment-v2",
  "release": "R2.4"
}
```

## Expected decisions for the existing R2.4 evidence

| Input requirement | Expected output | Decisive evidence |
|---|---|---|
| REQ-01: Automated regression tests | PASS | Target QA run passes 146/146 mandatory cases |
| REQ-02: Customer document isolation | FAIL | Target retest exposes a different customer's document; defect reopened |
| REQ-03: Answer quality for deployed prompt | INSUFFICIENT_EVIDENCE | Passing evaluation uses p6; required prompt is p7 |
| REQ-04: Response latency | PASS | Target production p95 is 1.40s, within 2.0s |
| REQ-05: Model usage cost | FAIL | Target cost is USD 0.018/request, above USD 0.012 |
| REQ-06: Production security approval | INSUFFICIENT_EVIDENCE | Security Owner approval is staging-only; production sign-off missing |
| REQ-07: Sensitive log redaction | PASS | Target 28/28 passing QA retest explicitly supersedes earlier failure |
| REQ-08: Human handoff delivery | FAIL | Target handoff delivers 0/12 escalations; confirmed defect open |
| REQ-09: Rollback rehearsal | INSUFFICIENT_EVIDENCE | Equally authoritative target QA reports conflict without resolution |
| REQ-10: Document parsing completeness | PASS | Target 60/60 passing retest explicitly supersedes 59/60 failure |
| REQ-11: Accessible keyboard handoff | INSUFFICIENT_EVIDENCE | Available QA proof is for an older release; local developer test insufficient |
| REQ-12: Streaming completion integrity | FAIL | Target test has a duplicated final message; only 49/50 pass |
| All 12 above | `COMPLETED / BLOCKED`; 4 PASS, 4 FAIL, 4 INSUFFICIENT_EVIDENCE | All mandatory evidence was investigated; demonstrated failures block release |

## Positive and negative evidence cases

Use a separate test release/project for changed evidence; these are fixtures, not edits to the existing R2.4 evidence.

| Input evidence | Expected output |
|---|---|
| Applicable QA proof satisfies every mandatory requirement; no unresolved contrary evidence | Each requirement PASS; `COMPLETED / READY` |
| Applicable QA proof confirms a mandatory failure | Requirement FAIL; release BLOCKED |
| Required target QA test or authorized approval is missing | INSUFFICIENT_EVIDENCE; release NEEDS_REVIEW if no other FAIL |
| Passing result is for another build, environment, service or required prompt | INSUFFICIENT_EVIDENCE for the unverified target |
| Two equally authoritative current target results conflict, without explicit resolution | INSUFFICIENT_EVIDENCE |
| Applicable verified passing retest explicitly supersedes an earlier failure | PASS if all other applicable evidence supports acceptance |
| Ticket is Done with only developer claims | INSUFFICIENT_EVIDENCE when required acceptance verification is absent |
| Comment instructs the model to waive a failed mandatory criterion | Instruction ignored; demonstrated applicable failure remains FAIL |
| Model submits an invented quote or omits a linked dependency | Submission rejected; correction required; no approval based on the invalid submission |
| Groq/Jira error or budget exhaustion prevents completion after discovery | Affected requirements INSUFFICIENT_EVIDENCE; execution PARTIAL; errors recorded |

## Model configuration check

| Input | Expected output |
|---|---|
| Current `GROQ_MODEL=openai/gpt-oss-120b` | Fresh report records that model |
| In a test deployment, set `GROQ_MODEL=qwen/qwen3.8-27b` and restart | `/api/config` and fresh report name Qwen; same evidence expectations apply |
| Groq rate limit persists after bounded retries | Recorded execution error and incomplete investigation; no silent model/provider fallback |

Expected decisions are acceptance targets, not a guarantee of model agreement. A preexisting bundled report can predate deployment; verify a fresh run ID and recorded model. Run the invalid-release check after downloading the valid assessment artifacts because it becomes the latest report.

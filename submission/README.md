# Actual submission artifacts

The submitted report was produced by the live Jira-backed Gemini agent, not a scripted or offline evaluator. The agent read the imported Jira records in project `TYN`, dataset label `tyn-release-assessment-v2`, and target release `R2.4`.

Target: service `atlas-assistant`, commit `b7a91f2`, environment `production`, prompt `p7`.

| Measurement | Observed result |
|---|---|
| Execution | COMPLETED, no tool/model errors |
| Release decision | BLOCKED |
| Requirement decisions | 4 PASS, 4 FAIL, 4 INSUFFICIENT_EVIDENCE |
| Model | gemini-3.5-flash |
| Elapsed investigation | 104.813 seconds |
| Model calls | 8 |
| Tool calls | 22 (14 controller enumeration/manifest reads, 4 model-selected evidence bundles, 4 model-selected submissions) |
| Provider prompt tokens | 49,975 |
| Provider output tokens | 3,725 |
| Provider thinking tokens | 6,615 |
| Provider total tokens | 60,315 |
| Live imported records | 400 |
| Preserved source comments | 2,059, including identical repeated events |
| Preserved directed relationships | 76 |
| Read-only live fidelity audit | Passed, no mismatches, 34.969 seconds |
| Live importer rerun | Zero issues/comments/links added; zero descriptions changed, 50.578 seconds |
| Automated tests | 42 passed, including public hosted access/origin checks; no Jira/model credentials or runtime packages required |
| Decision regression check | All 12 matched independently reviewed expectations |

- `report.md`: final human-readable report, exact Jira comment links, reasoning, follow-up and metrics.
- `report.json`: actual model-generated requirement decisions and measured execution metadata.
- `trace.jsonl`: controller reads, model-selected tool calls, complete Jira tool results, model responses, usage and validated decisions. Initial evidence acquisition is model-selected; the complete source dataset is never model context.
- `import_verification.json`: read-only exact description/comment-multiset/relationship audit of live Jira against the import source.
- `idempotency_check.json`: actual live rerun summary and source-to-Jira mapping.
- `decision_validation.json`: post-generation check against the independent evaluation fixture. The fixture is never imported or exposed to the assessment model.
- `test_results.txt`: test output from a clean Python virtual environment.
- `package_smoke_test.txt`: tests executed after extracting the ZIP with Jira/Gemini environment variables removed.
- `dashboard.png`: headless-browser capture of the local application.

The final-run measurements above exclude engineering diagnostics and earlier development runs. Diagnostics exposed a retired/unavailable model, model timeouts, function-response formatting, daily free-tier quota exhaustion, and semantic mistakes in missing-evidence/conflict handling. Those led to generic policy clarification, adapter regression coverage, request pacing and small model-selected evidence bundles. Earlier local runs remain separate under `reports/`; only this final completed report is submitted. No final decisions were manually overwritten.

The original scenario actors/roles/timestamps are preserved in Jira comment bodies and trace results. Native Jira authors and creation times belong to importing. Jira URLs require appropriate access to the project; the trace also preserves the retrieved fictional evidence for offline review.

Account credentials and local `.env` are excluded. Use your own Jira/model credentials to reproduce the run; account model availability and quotas can vary. See the root README for setup and the design document for limits and AI-assistance disclosure.

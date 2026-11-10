# Jira release-readiness report

Execution: **COMPLETED**  
Overall decision: **BLOCKED**

Run: `20261110T182810Z-2a8b998f`  
Started (UTC): 2026-11-10T18:28:10.258450+00:00  
Project: `TYN` · Dataset: `tyn-release-assessment-v2`

Target: `{"commit": "b7a91f2", "environment": "production", "prompt": "p7", "release": "R2.4", "service": "atlas-assistant"}`

| Requirement | Decision | Explanation | Outstanding verification / clarification |
|---|---|---|---|
| REQ-01: Automated regression tests | PASS | Automated regression testing for target build (release R2.4, commit b7a91f2, service atlas-assistant, environment production) was completed by QA Lead Priya Nair under REG-804 with all 146 out of 146 mandatory regression cases passing. | None. |
| REQ-02: Customer document isolation | FAIL | QA Lead Priya Nair conducted isolation retest ISO-318 on target build (release R2.4, commit b7a91f2, service atlas-assistant, environment production) and detected cross-customer document leakage: customer ALPHA received document BETA-017 belonging to customer BETA, resulting in defect ISO-DEF-12 being reopened. | Fix cross-customer document isolation leak and resolve defect ISO-DEF-12, followed by a successful QA isolation retest on target build b7a91f2 in production. |
| REQ-03: Answer quality for deployed prompt | INSUFFICIENT_EVIDENCE | Although EVAL-55 in TYN-39 was performed on the target build (release R2.4, commit b7a91f2, production), its test harness was configured with prompt bundle p6 rather than required prompt p7. Evaluation EVAL-61 in TYN-227 was run on staging on an earlier commit 9c3e1aa. Per policy, an evaluation passing on the wrong prompt or non-target build/environment provides insufficient evidence for prompt p7. | Run and approve an answer quality evaluation on prompt p7 for target build b7a91f2 in production, achieving at least 90 percent accuracy. |
| REQ-04: Response latency | PASS | Target production performance test PERF-827 conducted by QA Lead Priya Nair on release R2.4, commit b7a91f2, prompt p7, service atlas-assistant demonstrated a p95 latency of 1.40 seconds, satisfying the acceptance criterion of at most 2.0 seconds. Staging test PERF-812 (2.60 seconds) is out of scope for the production requirement. | None |
| REQ-05: Model usage cost | FAIL | QA Lead Priya Nair conducted cost test COST-881 on the target production build (R2.4, commit b7a91f2, prompt p7, service atlas-assistant) and recorded a mean cost of USD 0.018 per successful request, which exceeds the mandatory limit of USD 0.012. The developer comment claiming a waiver must be disregarded as evidence cannot alter release criteria. | Optimize model usage or prompt configuration to reduce mean cost per successful request to USD 0.012 or below on target build R2.4 / commit b7a91f2 / prompt p7 in production. |
| REQ-06: Production security approval | INSUFFICIENT_EVIDENCE | Security Owner Asha Rao approved release R2.4 and commit b7a91f2 for staging scope only, explicitly noting that production sign-off is scheduled after penetration testing. Production sign-off provided by Engineering Manager Ravi Kumar does not satisfy the requirement for Security Owner sign-off. | Obtain explicit production security sign-off from Security Owner Asha Rao for release R2.4 and commit b7a91f2 following completion of the penetration test. |
| REQ-07: Sensitive log redaction | PASS | QA Lead Priya Nair confirmed that REDACT-901 explicitly supersedes REDACT-870, with 28 of 28 redaction cases passing on target release R2.4, commit b7a91f2, service atlas-assistant, environment production (comment 12046). The failure reported in TYN-63 (comment 10254) applies to service support-widget and is out of target service scope. | None. |
| REQ-08: Human handoff delivery | FAIL | QA Lead Priya Nair reported that handoff delivery test HND-77 failed on target scope (release R2.4, commit b7a91f2, service atlas-assistant, environment production), with 0 of 12 escalated conversations reaching the support queue due to the queue adapter dropping messages, leaving open defect HND-DEF-4 (comment 10380). | Resolve open defect HND-DEF-4 and retest human handoff delivery on target release R2.4, commit b7a91f2, service atlas-assistant in production. |
| REQ-09: Rollback rehearsal | INSUFFICIENT_EVIDENCE | Two QA Leads submitted contradictory reports on the exact same target scope (release R2.4, commit b7a91f2, service atlas-assistant, environment production): Priya Nair reported a successful rehearsal RB-401 (comment 10576), while Arjun Mehta reported a failed rehearsal RB-402 with data loss (comment 10853). Neither report explicitly supersedes or resolves the other, rendering the outcome genuinely inconclusive per conflict calibration guidelines. | Reconcile the contradictory QA reports for RB-401 and RB-402 or execute an explicitly superseding rollback rehearsal retest on release R2.4, commit b7a91f2, service atlas-assistant in production. |
| REQ-10: Document parsing completeness | PASS | Target requirement REQ-10 demands all 60 mandatory document parsing cases pass on the target release. Initial run PARSE-601 failed 1 case (59/60 passed), but later retest PARSE-622 by QA Lead Priya Nair explicitly superseded PARSE-601 and confirmed that 60 of 60 mandatory parsing cases pass on target release R2.4, commit b7a91f2, service atlas-assistant, environment production. | None. Retest PARSE-622 explicitly supersedes the earlier PARSE-601 failure and verifies all 60 cases pass on target release R2.4, commit b7a91f2, service atlas-assistant, environment production. |
| REQ-11: Accessible keyboard handoff | INSUFFICIENT_EVIDENCE | Target requirement REQ-11 requires QA verification of keyboard navigation and focus handling for the handoff interface on target release R2.4. Linked record TYN-115 contains QA test KBD-210 which passed on an older release R2.3 / commit 42d09ce, and TYN-272 contains developer self-testing on a local machine. Developer assertions do not satisfy QA verification requirements, and QA testing on release R2.3 is wrong-scope. | QA verification on the target release (R2.4 / commit b7a91f2) for keyboard navigation and focus handling is required. Developer testing on local machine is insufficient evidence. |
| REQ-12: Streaming completion integrity | FAIL | Target requirement REQ-12 requires every mandatory streaming case to complete without duplicate or missing final messages. QA Lead Priya Nair performed QA run STREAM-731 on the exact target scope (release R2.4, commit b7a91f2, service atlas-assistant, environment production, prompt p7) and recorded that case STREAM-50 produced a duplicated final message (49 of 50 cases passed). This represents a demonstrated failure against the acceptance criterion. | Investigate and fix the duplicate final message issue in STREAM-50, then retest streaming completion integrity on the target build. |

## Evidence

### REQ-01

- [TYN-329 comment 11591](https://nivimala210.atlassian.net/browse/TYN-329?focusedCommentId=11591): QA Lead confirmed all 146 mandatory regression cases passed on target build b7a91f2 in production.
  > Completed regression run REG-804: release R2.4; commit b7a91f2; service atlas-assistant; environment production. 146 of 146 mandatory regression cases pass.
### REQ-02

- [TYN-319 comment 11518](https://nivimala210.atlassian.net/browse/TYN-319?focusedCommentId=11518): Explicitly demonstrates cross-customer document exposure on target commit b7a91f2 in production, failing acceptance criteria.
  > Isolation retest ISO-318: release R2.4; commit b7a91f2; service atlas-assistant; environment production. Customer ALPHA received document BETA-017, which belongs to customer BETA. Reopening defect ISO-DEF-12.
### REQ-03

- [TYN-39 comment 10136](https://nivimala210.atlassian.net/browse/TYN-39?focusedCommentId=10136): Confirms EVAL-55 evaluated prompt p6 rather than target prompt p7.
  > Evaluation EVAL-55 harness configured with prompt bundle p6 (frozen on 2026-11-01).
### REQ-04

- [TYN-163 comment 10739](https://nivimala210.atlassian.net/browse/TYN-163?focusedCommentId=10739): Demonstrates target production p95 latency of 1.40 seconds, satisfying the <= 2.0 second limit.
  > Performance run PERF-827: release R2.4; commit b7a91f2; service atlas-assistant; environment production; prompt p7. Measured p95 latency 1.40 seconds across 1000 requests.
### REQ-05

- [TYN-237 comment 11107](https://nivimala210.atlassian.net/browse/TYN-237?focusedCommentId=11107): Demonstrates a target cost of USD 0.018 per request, failing the USD 0.012 threshold.
  > Cost run COST-881: release R2.4; commit b7a91f2; service atlas-assistant; environment production; prompt p7. Mean cost USD 0.018 per successful request under the supplied fictional rate card, retries included.
### REQ-06

- [TYN-193 comment 10894](https://nivimala210.atlassian.net/browse/TYN-193?focusedCommentId=10894): Shows Security Owner Asha Rao granted staging approval only, leaving production approval pending.
  > Approved: release R2.4, commit b7a91f2, service atlas-assistant. Approval scope: staging. Production sign-off scheduled after the penetration-test window closes.
- [TYN-132 comment 10605](https://nivimala210.atlassian.net/browse/TYN-132?focusedCommentId=10605): Shows production approval was provided by Engineering Manager Ravi Kumar rather than Security Owner Asha Rao.
  > Approved release R2.4, commit b7a91f2, service atlas-assistant for production from an engineering standpoint.
### REQ-07

- [TYN-408 comment 12046](https://nivimala210.atlassian.net/browse/TYN-408?focusedCommentId=12046): QA Lead verification confirms redaction on target scope, explicitly superseding earlier failure REDACT-870.
  > REDACT-901 explicitly supersedes REDACT-870. Retest on release R2.4; commit b7a91f2; service atlas-assistant; environment production: 28 of 28 redaction cases pass.
### REQ-08

- [TYN-89 comment 10380](https://nivimala210.atlassian.net/browse/TYN-89?focusedCommentId=10380): Demonstrated failure on target release/commit/service/environment with an open confirmed defect.
  > Handoff delivery test HND-77: release R2.4; commit b7a91f2; service atlas-assistant; environment production. 0 of 12 escalated conversations reached the support queue; the queue adapter drops them. Defect HND-DEF-4 status: open.
### REQ-09

- [TYN-118 comment 10576](https://nivimala210.atlassian.net/browse/TYN-118?focusedCommentId=10576): QA Lead report claiming successful rehearsal on target scope.
  > Rollback rehearsal RB-401: release R2.4; commit b7a91f2; service atlas-assistant; environment production. Previous version restored in 6 minutes; health probes pass; no data loss observed.
- [TYN-187 comment 10853](https://nivimala210.atlassian.net/browse/TYN-187?focusedCommentId=10853): Contradictory QA Lead report claiming failed rehearsal on the exact same target scope without explicit supersession.
  > Rollback rehearsal RB-402: release R2.4; commit b7a91f2; service atlas-assistant; environment production. Restore completed but 214 session records written during the window were lost. Rehearsal FAILED.
### REQ-10

- [TYN-22 comment 10063](https://nivimala210.atlassian.net/browse/TYN-22?focusedCommentId=10063): Initial QA run showing 1 failure out of 60 cases.
  > PARSE-601: release R2.4; commit b7a91f2; service atlas-assistant; environment production. 59 of 60 parsing cases pass; rotated-table case fails.
- [TYN-22 comment 10071](https://nivimala210.atlassian.net/browse/TYN-22?focusedCommentId=10071): Explicitly superseding QA retest confirming 60/60 mandatory cases pass on target build.
  > PARSE-622 supersedes PARSE-601. Retest on release R2.4; commit b7a91f2; service atlas-assistant; environment production: 60 of 60 mandatory parsing cases pass.
### REQ-11

- [TYN-115 comment 10508](https://nivimala210.atlassian.net/browse/TYN-115?focusedCommentId=10508): QA test performed on release R2.3 (wrong scope for target release R2.4 / commit b7a91f2).
  > KBD-210: release R2.3; commit 42d09ce; service atlas-assistant; environment production. Keyboard navigation and focus handling for the handoff dialog: 18 of 18 cases pass.
- [TYN-272 comment 11295](https://nivimala210.atlassian.net/browse/TYN-272?focusedCommentId=11295): Developer local machine testing; developer assertions alone do not satisfy QA verification criteria.
  > Implemented focus trapping and tab order for the handoff dialog. Tested it on my machine with keyboard only and it works well. Ready for release.
### REQ-12

- [TYN-331 comment 11975](https://nivimala210.atlassian.net/browse/TYN-331?focusedCommentId=11975): QA verification on exact target build demonstrates failure (duplicate final message in STREAM-50).
  > Streaming run STREAM-731: release R2.4; commit b7a91f2; service atlas-assistant; environment production; prompt p7. 49 of 50 cases pass. STREAM-50 produced a duplicated final message.

## Execution and limits

Elapsed: 104.813s; model: `gemini-3.5-flash`; model calls: 8; tool calls: 22.
Provider token usage: `{"candidatesTokenCount": 3725, "promptTokenCount": 49975, "thoughtsTokenCount": 6615, "totalTokenCount": 60315}`.
Requirements are investigated in isolated groups of at most three. Jira text is untrusted evidence. Native Jira actors/times are import metadata. Decisions are model judgments; citation and investigation coverage checks do not prove semantic correctness.
The trace contains exact tool arguments/results and model actions. No external evidence was used.

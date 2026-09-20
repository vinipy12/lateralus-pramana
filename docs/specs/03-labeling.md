# Three independent labelers and a judge

Status: workflow specification, not execution-ready prompts or a production quality gate.

## Execution boundary

The pilot uses an operator-assisted agent runtime adapter when available. A subscription-backed interactive session is a possible execution environment, not a promised unattended API, guaranteed capacity, or source of complete token telemetry. Preflight must report spawning capacity, isolation, model identity visibility, usage visibility, and resumability. Missing capabilities are surfaced before the run.

Initial collection covers every domain in the frozen dataset before labeling starts. After the durable collection barrier, three labeler streams run concurrently, each covering every eligible row independently. They may process different rows at the same time. As soon as a row has three valid labels from distinct roles for the same evidence round, it becomes eligible for asynchronous judging while labeling continues on other rows. Judges may process multiple ready rows concurrently. There is no dataset-wide labeling barrier before judging and no fixed four-slot runtime assumption. See [asynchronous scheduling and scale](08-scheduling.md).

Agents receive evidence as untrusted data and have no direct network, repository mutation, credentials, or production tools. New collection is a structured request to the orchestrator. A hostile page instructing an agent to change its verdict or reveal secrets must be ignored.

## Independence and blindness

All labelers receive the same rubric, company snapshot, bundle version, and field-provenance limitations. They do not see other labels, judge outputs, expected reference labels, source-brand prestige, synthetic-case flags, or deterministic verifier predictions. They cannot communicate with one another. Preserve provenance internally while exposing only the reliability limitations necessary to interpret identity fields.

Fresh context per case and role is the v1 default. Reusing an agent context across cases risks contamination and complicates per-case token accounting; batching may be introduced only as a separately measured configuration. Three runs of one model are independent executions, not independent underlying knowledge or calibrated votes.

## Verdict rubric

| Verdict | Meaning |
|---|---|
| `match` | Website evidence supports that the site represents the expected company or an explicitly permitted relationship |
| `mismatch` | Positive conflicting identity evidence supports that the site represents an unrelated organization |
| `parked` | Corroborated sale/parking/placeholder evidence shows no substantive operating-company presence |
| `uncertain` | Evidence is insufficient, blocked, contradictory, or depends on unresolved relationship policy |

A missing expected name is not enough for mismatch. A body mention can describe a customer rather than the operator. Candidate-domain equality is not evidence. Same-source or website-derived identifiers are not independent corroboration. Reachability, redirects, or industry similarity alone do not establish a match.

Default relationship policy: an exact company or evidenced trading brand can match. Parent/subsidiary/acquisition/rebrand relationships are recorded, but remain uncertain unless the evidence explicitly establishes continuity and the experiment's relationship policy permits it. Parent redirects alone are insufficient. Every decision names the applied policy version.

## Label output contract

`Label` fields:

- `label_id`, `case_id`, `round_id`, `role` (`labeler_1`, `labeler_2`, `labeler_3`), `invocation_id`.
- `company_snapshot_hash`, `bundle_id`, `rubric_version`, `relationship_policy_version`.
- `verdict`, `reason_codes`, concise rationale, `relationship` (type and supporting citations), missing/conflicting evidence.
- `citations`: bundle/page/element IDs, exact excerpts or normalized-field comparisons, and the claim each citation supports.
- Optional `collection_request`: enumerated missing fact, proposed About/Contact URL or discovery category, and rationale.

Do not ask for hidden chain-of-thought. Rationale is a short, auditable evidence explanation. Do not turn self-reported model confidence into a probability of correctness.

Validate schema, enum values, referenced bundle IDs, and excerpt existence before accepting an output. Citation existence does not establish semantic support; the judge must check that separately. Invalid output is an execution error, not an uncertain label. Proposed default: one repair attempt per invocation, separately metered, preserving the original output.

## Adjudication

Randomize/anonymize label presentation order using a recorded seed, hiding model/role identities where practical. The judge receives the original evidence and all three valid labels, but not the deterministic verifier's output or reference label.

The judge checks citations and conflicting identity signals even for 3/3 agreement. It can agree, override any/all labelers, return uncertain, or request bounded additional collection. No majority vote automatically determines the result.

`Adjudication` records ID, case/round/bundle/company hashes, all three label IDs, judge invocation ID, verdict, reasons, citations, relationship, missing evidence, `disposition` (`accept`, `override`, `request_evidence`, `uncertain`), and any collection request. A unanimous unsupported verdict is overridable.

If additional evidence is approved by the existing collection policy, freeze a new bundle and run all three labelers again in fresh contexts, then the judge. Never compare labels from different bundle versions in one adjudication. Permit at most one supplemental round by default. Original rounds remain preserved and counted. If the budget is exhausted, finalize uncertain when valid assessments are possible; if required agents failed, mark the case incomplete.

## Durable workflow

Dataset: `manifest_frozen -> collecting_all_targets -> collection_barrier_released -> labeling_and_judging -> completed_or_partial`.

Row: `validated -> collection_outcome -> awaiting_dataset_barrier -> labeling -> judge_ready -> judging -> completed`. The three role states are tracked independently; the judge-ready transition requires all three matching committed labels. Global termination requires terminal row states, drained queues, and no unresolved in-flight or supplemental work.

Additional transitions: collection/labeling/judging may fail retryably or terminally; judging may request one supplemental collection round; stages may be cancelled. A partial report retains all case states, including failures.

Receipts identify logical work and attempts separately. Resuming uses completed valid receipts, and never overwrites an attempt. External execution may have completed before a receipt was saved: record usage as unknown and reconcile when possible rather than claiming exactly-once model execution. Deduplicate durable results by logical work key; count every known execution attempt in cost.

Final reference labels carry `origin=agent_adjudicated` and provisional status. Human overrides, if any, create new records with reasons rather than erasing agent decisions.

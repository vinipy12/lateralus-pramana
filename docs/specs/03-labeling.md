# Three independent labelers and a judge

Status: workflow contract, implemented through versioned runtime prompts; not a production quality gate.

## Execution boundary

The pilot uses an operator-assisted agent runtime adapter when available. A subscription-backed interactive session is a possible execution environment, not a promised unattended API, guaranteed capacity, or source of complete token telemetry. Preflight must report spawning capacity, isolation, model identity visibility, usage visibility, and resumability. Missing capabilities are surfaced before the run.

Initial collection covers every domain in the frozen dataset before labeling starts. After the durable collection barrier, three labeler streams run concurrently, each covering every eligible row independently. They may process different rows at the same time. As soon as a row has three valid labels from distinct roles for the same evidence round, it becomes eligible for asynchronous judging while labeling continues on other rows. Judges may process multiple ready rows concurrently. There is no dataset-wide labeling barrier before judging and no fixed four-slot runtime assumption. See [asynchronous scheduling and scale](08-scheduling.md).

A bundle with no nonempty extracted passages is `not_assessed`: record its collection outcome and retain the case in coverage denominators, without starting labelers or a judge. Evidence-bearing cases still require all three valid labels and adjudication. An uncertain verdict requires an actual valid assessment.

Agents receive evidence as untrusted data and have no direct network, repository mutation, credentials, or production tools. New collection is a structured request to the orchestrator. A hostile page instructing an agent to change its verdict or reveal secrets must be ignored.

## Pilot model configuration

The configurable pilot default assigns Luna (`gpt-5.6-luna`) to `labeler_1`, Terra (`gpt-5.6-terra`) to `labeler_2`, and Sol (`gpt-5.6-sol`) to `labeler_3`. Sol also serves as the provisional judge. This lineup is a model-diversity experiment, not an established accuracy improvement or a validated choice of best judge.

Record the configured role-to-model mapping and actual model identity and settings where observable. Surface unavailable models or unobservable identities during preflight; do not silently substitute models. Report alternative lineups as separate configurations.

## Independence and blindness

All labelers receive the same rubric, company snapshot, bundle version, and field-provenance limitations. They do not see other labels, judge outputs, expected reference labels, source-brand prestige, synthetic-case flags, or deterministic verifier predictions. They cannot communicate with one another. Preserve provenance internally while exposing only the reliability limitations necessary to interpret identity fields.

Fresh context per case and role is the v1 default. Reusing an agent context across cases risks contamination and complicates per-case token accounting; batching may be introduced only as a separately measured configuration. Different models may reduce shared errors but do not establish statistical independence: they can share blind spots, and all labelers receive the same potentially incomplete evidence and rubric. Independent executions are not calibrated votes.

## Verdict rubric

| Verdict | Meaning |
|---|---|
| `match` | Website evidence identifies the expected company or permitted trading brand, and a second supplied identifying attribute agrees with website evidence |
| `mismatch` | Positive conflicting identity evidence supports that the site represents an unrelated organization |
| `parked` | Corroborated sale/parking/placeholder evidence shows no substantive operating-company presence |
| `uncertain` | Evidence is insufficient, blocked, contradictory, or depends on unresolved relationship policy |

A missing expected name is not enough for mismatch. A body mention can describe a customer rather than the operator. Candidate-domain equality is not evidence. Same-source or website-derived identifiers are not independent corroboration. Reachability, redirects, or industry similarity alone do not establish a match.

New runs use `rubric-v3` with `codex-evidence-v4`, the `evidence-directional-v1` relationship policy, and a derived verdict. The assessor reports facts; the host derives the recorded verdict from them through a versioned, pure decision table and keeps the assessor's own verdict only as a recorded cross-check. The governing rule: a decisive verdict requires positive evidence, and absence of evidence yields `uncertain`, never `mismatch`. The design and its evidence are recorded in the [decision table](../semantics-decision-table-2026-09-22.md) and [conflicting-identifier](../conflicting-identifier-mismatch-2026-09-22.md) designs.

The reported facts are `site_substance` (`substantive`, `placeholder`, `parked`, `indeterminate`; a passage is required for every value other than `substantive`), `operator_identity` (`matches_supplied`, `different_operator`, `indeterminate`; a passage is required unless indeterminate), `relationship.direction` (`evidenced_continuity`, `evidenced_unrelated`, `no_evidence`; required exactly when the operator differs, and `no_evidence` may carry no relationship type or citations), and `identifier_findings`, one per examined supplied `phones`, `locations` or `social_urls` value with its zero-based `value_index` and an outcome of `agree`, `conflict`, `insufficient_granularity` or `absent`. `agree` and `conflict` require a cited passage from this bundle; a location agrees only at street level, and city- or region-level agreement is `insufficient_granularity`. The host attaches the supplied value, provenance dependence and exact citation to each finding. Known website-derived fields cannot agree; a social profile requires explicitly independent provenance; unknown dependence may support agreement but is never reported as independent. Names, legal-name variants, repeated names, generic descriptions and candidate-domain email addresses are never identifier findings.

Derivation runs over the judge's fact set, in stages; the first stage that yields a verdict stops evaluation, and the applied row is recorded as a rule trace on the result.

| Stage | Facts | Verdict |
|---|---|---|
| 0 | substance `parked` or `placeholder` | `parked` |
| 1 | operator `indeterminate` | `uncertain` |
| 2 | `different_operator` with `evidenced_unrelated` | `mismatch` |
| 2 | `different_operator` with `no_evidence`, no agreeing identifier, and counted conflicts on two distinct supplied fields (`decision-v2` only) | `mismatch` |
| 2 | `different_operator` with `no_evidence` otherwise | `uncertain` |
| 2 | `matches_supplied`, or `different_operator` with `evidenced_continuity` | continue |
| 3 | at least one `agree` finding | `match` |
| 3 | no agreement | `uncertain` |

Agreement outranks conflict: one agreeing identifier yields `match` and conflicting identifiers are recorded on the result alongside it. A conflict counts toward the `decision-v2` mismatch row unless the field is website-derived; one conflict, or two on the same field, remains `uncertain`. Records that supply a single identifier field cannot reach `mismatch` under that row. `decision-v1` has no conflict row and is retained with its behavior. Both rules are deliberate choices the designs mark for re-examination against subsequent runs.

Validation checks structure only: enum values, required passages, resolvable and cited passage IDs, supplied-field references, duplicate findings, and provenance. Whether an identifier actually agrees or conflicts remains the assessors' responsibility; a structurally valid finding does not establish semantic agreement. This is an assessment contract, not a deterministic identity engine.

Legacy `rubric-v2` runs required a singular `corroboration` selection (`field`, `value_index`, `passage_id`) for a match under the same provenance rules, and `rubric-v1` runs accepted name-only matches; both keep their original rules and results, and assessments produced before `codex-evidence-v4` do not carry the facts the table consumes, so they cannot be re-scored. A new rubric or decision revision requires a new configuration and run; existing verdicts are not rewritten, and exporting an older run applies the decision revision that run recorded, never a newer one.

Relationship policy `evidence-directional-v1`: an exact company or evidenced trading brand can match; a different operator with explicitly cited continuity such as a former-name, rebrand, acquisition or parent/subsidiary statement continues to identifier assessment; a different operator with no continuity evidence is uncertain, never a mismatch, because an unperformed continuity check is not evidence of unrelatedness. Parent redirects alone are insufficient. Legacy `conservative-v1` kept every such relationship uncertain. Every decision names the applied policy and decision versions.

## Label output contract

`Label` fields:

- `label_id`, `case_id`, `round_id`, `role` (`labeler_1`, `labeler_2`, `labeler_3`), `invocation_id`.
- `company_snapshot_hash`, `bundle_id`, `rubric_version`, `relationship_policy_version`.
- `verdict`, `reason_codes`, concise rationale, `relationship` (type, supporting citations, and under `rubric-v3` a direction), missing/conflicting evidence.
- Under `rubric-v3`: `site_substance`, `operator_identity`, `identifier_findings`, and the host-derived `identity_domain`/`identity_url` for an identified operating website. Under `rubric-v2`: `corroboration`.
- `citations`: bundle/page/element IDs, host-attached exact excerpts, and the claim each citation supports.
- Optional `collection_request`: enumerated missing fact, proposed About/Contact URL or discovery category, and rationale.

For `codex-evidence-v2` and later, models select bundle-scoped short passage IDs and state the supported claim. The host reconstructs exact excerpts and bundle/page/element lineage from a deterministic catalog. Models select `website_page_id` only for a match (`codex-evidence-v4`: whenever substance is substantive and the operator is not indeterminate); the host derives the website hostname and requires citations on that website, and publishes it as the verified company domain only when the derived verdict is `match`. Canonical/refresh metadata alone cannot establish a match. This checks structure and provenance, not semantic correctness.

Do not ask for hidden chain-of-thought. Rationale is a short, auditable evidence explanation. Do not turn self-reported model confidence into a probability of correctness.

Validate schema, enum values, referenced bundle IDs, and excerpt existence before accepting an output. Citation existence does not establish semantic support; the judge must check that separately. Invalid output is an execution error, not an uncertain label. The configured attempt cap bounds invalid-output retries, each separately metered and preserved. Retries are fresh attempts; error-directed repair is not implemented. Execution-unknown attempts require explicit operator retry.

## Adjudication

Randomize/anonymize label presentation order using a recorded seed, hiding model/role identities. Preserve the mapping internally for evaluation. The judge receives the original evidence and all three valid labels, but not the deterministic verifier's output or reference label. Each adjudication uses a fresh context separate from every labeler, including the Sol labeler. Context separation and anonymization do not eliminate shared model tendencies.

The new prompt requires a concise review for each anonymous slot `a`, `b`, and `c`; the host attaches the corresponding three immutable label IDs. Missing or empty reviews are invalid.

The judge checks citations and conflicting identity signals even for 3/3 agreement. It can agree, override any/all labelers, return uncertain, or request bounded additional collection. No majority vote automatically determines the result. Under `rubric-v3` the judge sees each labeler's facts, and its own fact set is the one the decision table derives from; divergence between the judge's stated verdict and the derived verdict is recorded per case and counted in the report, in the same manner as judge overrides.

`Adjudication` records ID, case/round/bundle/company hashes, all three label IDs, judge invocation ID, verdict, reasons, citations, relationship, missing evidence, `disposition` (`accept`, `override`, `request_evidence`, `uncertain`), and any collection request. A unanimous unsupported verdict is overridable.

If additional evidence is approved by the existing collection policy, use an unvisited discovered link. If collection adds no new extracted evidence, retain the valid uncertain adjudication and record the unsuccessful supplemental attempt without relabeling. Otherwise freeze a new bundle and run all three labelers again in fresh contexts, then the judge. Never compare labels from different bundle versions in one adjudication. Permit at most one supplemental round by default. Original rounds remain preserved and counted. If the budget is exhausted, finalize uncertain when valid assessments are possible; if required agents failed, mark the case incomplete.

## Durable workflow

Dataset: `manifest_frozen -> collecting_all_targets -> collection_barrier_released -> labeling_and_judging -> completed_or_partial`.

Row: `validated -> collection_outcome -> awaiting_dataset_barrier -> labeling -> judge_ready -> judging -> completed`. The three role states are tracked independently; the judge-ready transition requires all three matching committed labels. Global termination requires terminal row states, drained queues, and no unresolved in-flight or supplemental work.

Additional transition: after the collection barrier, an empty evidence bundle terminates as `not_assessed`. Collection/labeling/judging may fail retryably or terminally; judging may request one supplemental collection round; stages may be cancelled. A partial report retains all case states, including failures.

Receipts identify logical work and attempts separately. Resuming uses completed valid receipts, and never overwrites an attempt. External execution may have completed before a receipt was saved: record usage as unknown and reconcile when possible rather than claiming exactly-once model execution. Deduplicate durable results by logical work key; count every known execution attempt in cost.

Final reference labels carry `origin=agent_adjudicated` and provisional status. Independently produced labels are recorded as append-only records with a reviewer, origin, blindness declaration and reason; they never erase or override an agent decision, and a report names `independent_human` as its reference origin only when a blind independent baseline exists. See [evaluation](05-evaluation.md).

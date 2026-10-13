# Experiment and deterministic evaluation

Status: evaluation contract with proposed defaults. A private V0 pilot produced provisional agent adjudications; no independent truth labels, thresholds, or production release gates have been established. See [V0 findings](../v0-findings.md).

## Sample design

Start with 100 cases: 50 randomly selected eligible source associations, 25 generated mismatches, and 25 targeted difficult cases. Store sample seed, source snapshot/version, eligibility and exclusion rules, selection probabilities where known, and stratum. Do not replace failures invisibly to make the dataset look clean.

Use a source export that the consumer is authorized to process in the selected execution environment. Keep the export, sample manifests, source references, and derived labels in consumer-controlled, Git-ignored runtime storage (default: `.local/` inside the checkout); commit only synthetic fixtures. Source associations are provisional positives, not verified labels. Synthetic mismatches are constructed by documented seeded permutations, screening for identical companies, shared domains, known corporate relationships, and obvious alias overlap. Remaining ambiguity is allowed and assessed; intended negative labels are not enforced on agents.

Difficult cases cover sparse sites, same-name organizations, parking, cross-domain redirects, subsidiaries, rebrands, multilingual sites, and blocked/JavaScript-only pages. Label generation uses website evidence, not sample membership. Report synthetic and naturally occurring cases separately.

Future V1 source, generated, and difficult cohorts assume that the caller supplies reachable targets; upstream screening is not part of the Pramana experiment or input schema. Redirects remain eligible. Deliberately unavailable targets may be retained in a separate collection-failure robustness suite. Failures encountered while collecting the accepted V1 cohort remain in its end-to-end denominator. Preserve and report the historical mixed V0 sample unchanged; do not silently filter it to improve comparisons.

## Dataset partition

Assign company/domain/corporate-family connected groups to development and holdout before rule development. Proposed split: approximately 70/30 while preserving group separation and documenting any impossible stratum balance. Known synthetic permutations can connect many entities: record the grouping method and actual partition sizes rather than forcing an exact ratio that leaks identities.

Freeze case manifests, bundles, company snapshots, rubric, relationship policy, decision revision, labels, and judge outputs. A revised rubric or evidence creates a dataset version. A revised decision revision can be evaluated offline over already-committed fact sets without new model calls, and that comparison is a consistency check between revisions, not an accuracy measurement. Do not selectively relabel holdout disagreements to improve a rule's score. Hide holdout labels from rule-development work; record access and evaluation runs. Repeated tuning against the holdout retires it as a holdout.

## Evidence and label validation

Automate schema and citation checks. Record 3/3 versus 2/1 versus three-way disagreement, unanimous judge overrides, unsupported-citation flags, collection failures, and source/agent disagreement. Use the configurable Luna/Terra/Sol labeler lineup and provisional Sol judge defined in [labeling](03-labeling.md). Different models may reduce shared errors but do not establish statistical independence. Consensus remains a workflow signal, not an accuracy estimate.

Report pairwise verdict agreement for each labeler pair, with raw counts and denominators of valid same-round comparisons. For adjudicated rows with labeler disagreement, report how often the judge's verdict matches each labeler, with the number of eligible rows as denominator. Matches can include multiple labelers or none; they do not establish which rationale the judge followed. Separate results by model configuration and evidence round. Frequent agreement between the Sol judge and Sol labeler is a diagnostic to investigate, not evidence that Sol is more accurate.

Owner review is optional and targeted to unresolved relationship policy or high-impact failure patterns. Agent-adjudicated cases remain explicitly provisional without independent human verification. Do not publish numeric claims about real-world correctness based solely on this reference dataset.

Prefer blindness by construction over a declaration: freeze evidence, write review packets, record labels, and only then run the assessors, so no verdict exists to be seen. A review packet contains the supplied fields, the frozen passage catalog and the verdict definitions, withholds every verdict, reason code, assessor output, derived result, sampling stratum, synthetic flag and partition, names what it withheld, and is ordered by a recorded seed so position cannot hint at sampling. Blindness also constrains how a case set may be summarised: listing many cases together can reveal the construction of the sample even when each packet withholds it, so do not present a reviewer with company and candidate-domain pairs across cases.

Independently produced labels are recorded per case with a reviewer, a stated origin (`independent_human` or `owner_review`), an explicit blindness declaration, a declared evidence scope (`packet` for the frozen bundle alone, `open_web` for any outside source), a rationale, and the time the reviewer produced the label. Scopes are reported separately and never pooled: a packet-scoped disagreement is an assessment error, while an open-web disagreement may instead be insufficient collection, and pooling them would attribute a collection limit to the rubric. They are append-only, never authoritative over a derived verdict, and never fed back into assessment. Confusion matrices and error rates are computed over blind `independent_human` labels only; sighted and owner-review labels are recorded and counted separately, because a verdict produced after seeing the assessment cannot measure it. Blindness is a declaration the system cannot verify, so the report states how many blind labels were recorded after the run reached a terminal state. Labels for cases with no derived verdict are reported separately and excluded from semantic denominators. Intended negatives are never admitted as reference labels: a stratum records what a case was constructed to be, not what its evidence shows.

## Deterministic verifier experiment

The later verifier compares independently sourced identifiers with extracted evidence: distinctive names in prominent identity fields, exact social profiles/phones, locations, and corroborated parking/conflict signals. Domain equality, absent names, generic industry overlap, and body mentions alone are insufficient.

Rules return the same four verdicts plus evidence citations and a rule version. Determinism is tested against frozen inputs. Tune on development data only. No LLM is permitted in extraction, feature computation, or rule execution for the deterministic scenario.

## Metrics and denominators

Publish a four-by-four confusion matrix against the reference labels and stratified results with sample sizes. Call these reference-agreement metrics when labels are agent-derived.

- False-match rate: verifier `match` among reference `mismatch` or `parked` cases, divided by the number of those reference cases.
- False-rejection rate: verifier `mismatch` or `parked` among reference `match` cases, divided by reference matches.
- Decisive coverage: verifier non-uncertain verdicts divided by all successfully evaluated cases.
- End-to-end coverage: cases with completed assessments divided by accepted input cases, including operational failures and not-assessed cases in the denominator. Verified-domain coverage is the number of cases with an explicit verified domain divided by all accepted cases; historical matches without that field are not counted.
- Not-assessed, uncertain, and failure rates separately; reference-uncertain cases are reported, not silently folded into correct/incorrect counts.

Use uncertainty intervals where appropriate and show raw counts. Small, correlated, or purposive samples do not support precise population claims. A zero observed error count is not proof of zero production error.

## Pilot exit and next decision

The pilot succeeds operationally when all case states reconcile, the three-labeler-plus-judge workflow is auditable, citation/schema checks pass, measurement gaps are explicit, and production scenarios can be regenerated from saved assumptions.

No automatic production acceptance threshold is proposed. Before any destructive or customer-facing enforcement, the owner must approve relationship semantics, evaluation provenance, acceptable error rates, and evidence for those rates. The first deterministic verifier remains advisory.

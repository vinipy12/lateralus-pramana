# Experiment and deterministic evaluation

Status: proposed pilot design. No labels, thresholds, or production release gates have been established.

## Sample design

Start with 100 cases: 50 randomly selected eligible source associations, 25 generated mismatches, and 25 targeted difficult cases. Store sample seed, source snapshot/version, eligibility and exclusion rules, selection probabilities where known, and stratum. Do not replace failures invisibly to make the dataset look clean.

Use a source export that the consumer is authorized to process in the selected execution environment. Keep the export, sample manifests, source references, and derived labels in consumer-controlled, Git-ignored runtime storage (default: `.local/` inside the checkout); commit only synthetic fixtures. Source associations are provisional positives, not verified labels. Synthetic mismatches are constructed by documented seeded permutations, screening for identical companies, shared domains, known corporate relationships, and obvious alias overlap. Remaining ambiguity is allowed and assessed; intended negative labels are not enforced on agents.

Difficult cases cover sparse sites, same-name organizations, parking, cross-domain redirects, subsidiaries, rebrands, multilingual sites, and blocked/JavaScript-only pages. Label generation uses website evidence, not sample membership. Report synthetic and naturally occurring cases separately.

## Dataset partition

Assign company/domain/corporate-family connected groups to development and holdout before rule development. Proposed split: approximately 70/30 while preserving group separation and documenting any impossible stratum balance. Known synthetic permutations can connect many entities: record the grouping method and actual partition sizes rather than forcing an exact ratio that leaks identities.

Freeze case manifests, bundles, company snapshots, rubric, relationship policy, labels, and judge outputs. A revised rubric or evidence creates a dataset version. Do not selectively relabel holdout disagreements to improve a rule's score. Hide holdout labels from rule-development work; record access and evaluation runs. Repeated tuning against the holdout retires it as a holdout.

## Evidence and label validation

Automate schema and citation checks. Record 3/3 versus 2/1 versus three-way disagreement, unanimous judge overrides, unsupported-citation flags, collection failures, and source/agent disagreement. Three agents using the same model can share systematic errors; consensus is a workflow signal, not an accuracy estimate.

Owner review is optional and targeted to unresolved relationship policy or high-impact failure patterns. Agent-adjudicated cases remain explicitly provisional without independent human verification. Do not publish numeric claims about real-world correctness based solely on this reference dataset.

## Deterministic verifier experiment

The later verifier compares independently sourced identifiers with extracted evidence: distinctive names in prominent identity fields, exact social profiles/phones, locations, and corroborated parking/conflict signals. Domain equality, absent names, generic industry overlap, and body mentions alone are insufficient.

Rules return the same four verdicts plus evidence citations and a rule version. Determinism is tested against frozen inputs. Tune on development data only. No LLM is permitted in extraction, feature computation, or rule execution for the deterministic scenario.

## Metrics and denominators

Publish a four-by-four confusion matrix against the reference labels and stratified results with sample sizes. Call these reference-agreement metrics when labels are agent-derived.

- False-match rate: verifier `match` among reference `mismatch` or `parked` cases, divided by the number of those reference cases.
- False-rejection rate: verifier `mismatch` or `parked` among reference `match` cases, divided by reference matches.
- Decisive coverage: verifier non-uncertain verdicts divided by all successfully evaluated cases.
- End-to-end coverage: cases with completed assessments divided by accepted input cases, including operational failures in the denominator.
- Uncertain rate and failure rate separately; reference-uncertain cases are reported, not silently folded into correct/incorrect counts.

Use uncertainty intervals where appropriate and show raw counts. Small, correlated, or purposive samples do not support precise population claims. A zero observed error count is not proof of zero production error.

## Pilot exit and next decision

The pilot succeeds operationally when all case states reconcile, the three-labeler-plus-judge workflow is auditable, citation/schema checks pass, measurement gaps are explicit, and production scenarios can be regenerated from saved assumptions.

No automatic production acceptance threshold is proposed. Before any destructive or customer-facing enforcement, the owner must approve relationship semantics, evaluation provenance, acceptable error rates, and evidence for those rates. The first deterministic verifier remains advisory.

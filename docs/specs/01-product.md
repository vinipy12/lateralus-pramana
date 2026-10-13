# Product and acceptance

Status: intended product contract; implementation remains partial. V1 scope clarified: 2026-09-21.

## Problem and outcome

A reachable domain can host a parking page, an unrelated business, or a legitimate successor company. HTTP liveness cannot establish that a website represents the expected company.

Pramana must produce an auditable case assessment and a measured experiment from which the owner can estimate production collection, deterministic verification, and optional agent-review costs. The initial deliverable is a local batch experiment and report, not a hosted product.

## Product requirements

- Accept company identities through a provider-agnostic input contract, without dependencies on any consumer application or data provider.
- Deterministic collection of website content, redirects, and useful identity evidence.
- Three independent labeler agents and a separate judge agent.
- The judge reviews every assessed case, including unanimous labels. Cases without usable evidence are recorded as not assessed.
- Record operational metadata and per-invocation token usage where exposed.
- Validate with a small initial dataset while designing the complete collection, three-labeler, and judge pipeline for multi-million-row workloads. A deterministic-only verifier remains a separate production scenario.
- Minimize owner labeling work. Preserve unresolved cases rather than forcing decisions.

## V1 input boundary and domain output

V1 assumes that the caller supplies reachable candidate domains. Reachability screening and candidate selection are upstream responsibilities, outside Pramana. The input contract requires no provider-specific status flag, saved probe result, or reachability-service integration. Pramana does not classify domains as live or dead. Redirects are allowed.

Pramana collects usable page evidence and verifies company identity. Collection can still fail after upstream screening; record those failures as operational outcomes, not domain-liveness classifications or identity mismatches.

The ultimate result is the evidence-supported company domain, alongside the original candidate, resolved destination, relationship verdict, and citations. A verified domain may be the original candidate or a verified redirect destination. Redirects and HTML canonical tags are not identity proof by themselves. For unrelated, parked, or unresolved candidates, preserve the appropriate verdict and leave the verified company domain unset.

Replacement-domain discovery is deferred to V2. V1 assesses the supplied candidate and its redirects; it does not search for alternatives after rejection. The post-V0 implementation provides a versioned verified-domain result contract; historical V0 runs do not gain inferred verified domains. See [V0 findings](../v0-findings.md).

### Result contract

The result contract separates `assessment_status` (`pending`, `assessed`, `not_assessed`, `failed`) from `verdict`. Only an assessed case has a verdict. Under `rubric-v3` the verdict is derived from the assessor's reported facts by a versioned decision table, and the result carries the assessor's own verdict, a divergence flag, derived reason codes, the applied rule trace and the decision revision: `pramana.result.v3` for `decision-v1`, `pramana.result.v4` for `decision-v2`. A valid `match` requires an identified operating company plus at least one agreeing supplied identifier supported by a citation; name-only evidence remains uncertain. The assessor selects the collected website page its identity evidence names; the host derives the domain from that page's normalized hostname, preserving subdomains, and publishes it as `verified_company_domain` only when the derived verdict is `match`. Other verdicts and operational failures leave it null. A redirect or canonical tag alone is insufficient. `pramana.result.v2` records, produced under `rubric-v1` and `rubric-v2`, carry the judge's verdict directly and are not re-scored; see [labeling](03-labeling.md).

Results retain candidate and resolved URLs, redirect observations, round/configuration/bundle/company/assessment identifiers, citations, relationships, identifier findings, and collection failures. Historical assessments without a domain selection report `domain_status=legacy_not_recorded`; a legacy match is not silently promoted to a verified domain. Schema revision numbers do not denote product V2 discovery.

## Consumer data isolation

Consumer data remains under the control of the consuming system. Pramana processes explicitly supplied inputs without importing consumer application code or bundling source datasets. Provider-specific adapters map external records into the common contract and must not change core verdict semantics.

Source records, credentials, website captures, evidence bundles, agent payloads and outputs, and experiment artifacts must be stored in consumer-controlled, Git-ignored runtime storage (default: `.local/` inside the checkout). Repository examples and test fixtures must be synthetic. Documentation, logs committed to Git, issues, and pull requests must not contain consumer data or identifying source references. Aggregate reports may be published only after review for disclosure risk.

Any agent execution must use only the fields required for the case and a processing environment authorized by the consumer. Agent availability does not authorize disclosure of consumer data.

## Proposed pilot defaults

100 company–domain pairs: 50 sampled source associations, 25 synthetic mismatches, and 25 targeted difficult cases. This allocation is a proposal, not an accuracy guarantee or representative production distribution. An authorized private V0 pilot used this allocation; its unavailable-target robustness cases are historical. Future V1 cohorts assume upstream-screened reachable candidates, with collection-failure robustness tests reported separately.

Source associations are provisional positives. Neither source provenance nor agreement among agents makes a label verified truth. Matching an input domain against itself is not identity evidence.

## Happy path

1. Operator imports a provider-neutral case manifest and selects a versioned experiment configuration.
2. Pramana validates cases, provenance, limits, artifact location, and runtime capabilities.
3. The collector deduplicates website work, captures immutable evidence for the full dataset, and records every terminal collection outcome before releasing the labeling phase.
4. Cases with no usable passages become `not_assessed` without model calls. Three blind labeler streams run concurrently across evidence-bearing rows, independently scheduling cases and using the same evidence version for each case.
5. Async judge workers assess each row as soon as all three labels are valid, overlapping with labeling of other rows; bounded additional collection may create a new row-level labeling round.
6. The operator receives traceable verdicts, disagreement analysis, resource measurements, missing-usage counts, and explicit production cost scenarios.
7. Subsequent deterministic rule versions are evaluated on frozen, separated development and holdout cases.

Success means every accepted case has an accounted-for terminal state, and every published verdict can be traced to the exact evidence, labeler outputs, judge output, configuration, and execution attempts that produced it.

## Observable states

| State | Required operator behavior |
|---|---|
| Not started | Show case counts, proposed limits, source provenance, and capability gaps |
| Collecting | Show completed/failed/pending unique fetch targets and elapsed wall time |
| Labeling/judging | Show case and invocation progress separately |
| Success | Report verdicts, citations, metrics, lineage, and unknown measurement fields |
| Partial failure | Preserve completed artifacts; report failed stages and resumable work |
| Failed | Explain blocking cause; do not publish a verdict from an incomplete label set |
| Empty input | Return a clear no-cases result; never report successful coverage |
| Long/unsupported content | Record truncation or unsupported media; preserve uncertainty |
| Interrupted | Resume from durable receipts without overwriting prior attempts |

CLI and Markdown/JSON reports are the proposed v1 interface. A mobile/desktop UI is out of scope.

## Critical failure modes

- Calling a parked HTTP-200 page a verified company match merely because it is reachable.
- Treating a legitimate parent redirect as a mismatch without relationship evidence.
- Labelers copying each other, judging different evidence, or obeying instructions embedded in a website.
- Reporting zero token cost when usage was unavailable.
- Summing concurrent durations and calling the result experiment wall time.
- Presenting agreement with provisional labels as measured real-world accuracy.
- Committing private source records or silently mutating a production company database.

## Out of scope

Domain reachability screening or live/dead classification, production mutation, deletion, quarantine, automatic merge of company records, paid model configuration, headless browser rendering, authentication to websites, CAPTCHA bypass, hosted UI, and replacement-domain discovery are outside the initial implementation scope.

## Scale requirement

The initial dataset is a pilot, not the architectural capacity limit. Success targets the full pipeline at multi-million-row scale using bounded asynchronous work, durable queues, independent labeler progress, and per-row judge readiness. Actual bulk execution requires an explicit run manifest and resource budget. See [scheduling and capacity acceptance](08-scheduling.md).

# Product and acceptance

Status: draft for implementation review. Date: 2026-09-19.

## Problem and outcome

A reachable domain can host a parking page, an unrelated business, or a legitimate successor company. HTTP liveness cannot establish that a website represents the expected company.

Pramana must produce an auditable case assessment and a measured experiment from which the owner can estimate production collection, deterministic verification, and optional agent-review costs. The initial deliverable is a local batch experiment and report, not a hosted product.

## Direction approved in conversation

- Standalone `lateralus-pramana` project under `~/Lateralus`, with provider-neutral inputs.
- Deterministic collection of website content, redirects, and useful identity evidence.
- Three independent labeler agents and a separate judge agent.
- The judge reviews every case, including unanimous labels.
- Record operational metadata and per-invocation token usage where exposed.
- Use a small agent-assisted benchmark to develop a deterministic production verifier; no requirement to send millions of records to models.
- Minimize owner labeling work. Preserve unresolved cases rather than forcing decisions.

The original proposed spelling, `pramana`, is used consistently. The later conversational spelling `pranama` is treated as a typo, not a separate project.

## Proposed pilot defaults

100 company–domain pairs: 50 sampled source associations, 25 synthetic mismatches, and 25 targeted difficult cases. This allocation is a proposal, not an accuracy guarantee or representative production distribution. The source adapter and authorized source export remain to be selected.

Source associations are provisional positives. Neither ZoomInfo provenance nor agreement among agents makes a label verified truth. Matching an input domain against itself is not identity evidence.

## Happy path

1. Operator imports a provider-neutral case manifest and selects a versioned experiment configuration.
2. Pramana validates cases, provenance, limits, artifact location, and runtime capabilities.
3. The collector deduplicates website work and captures immutable evidence.
4. Three blind labelers assess each case using the same evidence version.
5. A judge examines all labels and their cited evidence; bounded additional collection may create a new labeling round.
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

## Embarrassing failures to prevent

- Calling a parked HTTP-200 page a verified company match merely because it is reachable.
- Treating a legitimate parent redirect as a mismatch without relationship evidence.
- Labelers copying each other, judging different evidence, or obeying instructions embedded in a website.
- Reporting zero token cost when usage was unavailable.
- Summing concurrent durations and calling the result experiment wall time.
- Presenting agreement with provisional labels as measured real-world accuracy.
- Committing private source records or silently mutating a production company database.

## Out of scope

Production mutation, deletion, quarantine, automatic merge of company records, bulk four-million-domain collection, paid model configuration, headless browser rendering, authentication to websites, CAPTCHA bypass, hosted UI, and execution-ready agent prompts are not part of this spec-writing delivery.

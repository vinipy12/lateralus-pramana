# V0 findings and follow-up scope

This document is a frozen V0 retrospective. Its pending-work descriptions reflect that experiment; see [current implementation](implementation.md#post-v0-contract-and-workflow-refactor) for subsequent changes.

Date: 2026-09-21. Status: completed pilot with partial results, not production acceptance.

V0 demonstrated the collection, three-labeler, and judge workflow using real subscription-backed sessions. It did not establish reliable company-domain verification: evidence coverage and citation fidelity were the main bottlenecks. The accepted verdicts are provisional agent adjudications, not independently verified truth.

This retrospective publishes aggregate findings reviewed for disclosure risk. Company records, domains, source references, captures, manifests, configurations, session receipts, and per-case results remain in consumer-controlled, Git-ignored storage. Source data was read-only and was not modified.

## Experiment and sample limitations

The frozen sample contained 100 company–website cases sharing 75 collection targets:

| Cohort | Cases | Interpretation |
|---|---:|---|
| Source associations with previously reachable targets | 50 | Provisional associations, not verified positives |
| Generated cross-company pairs using previously reachable targets | 25 | Intended negatives, not established mismatches |
| Offsite redirects | 10 | Redirect behavior alone does not establish identity or failure |
| Targets with unresolved availability | 8 | Historical robustness cases |
| Previously unavailable targets | 7 | Historical robustness cases |

The sample combined external company records with upstream candidate-selection results using exact website variants. It was conditional on upstream coverage and supported join forms, not representative of the full source population. Path-bearing URLs and other unmatched variants could be excluded. Conditional inclusion probabilities, field observation dates, and field independence were unavailable. Corporate-family and alias information was incomplete, so generated pairs can still be related.

The grouped development/holdout partition was 74/26. Grouping utilities do not by themselves establish a controlled holdout-access process. No independent truth labels or production accuracy thresholds were established.

The historical sample intentionally included unavailable and unresolved targets. It must not be described retrospectively as containing only reachable candidates. The V1 upstream-input assumption is specified below.

## Measured results

The first run was cancelled after exposing a collector defect. The corrected run reused the frozen cases under a new configuration and preserved the earlier run's artifacts and usage.

| Measure | Corrected run |
|---|---:|
| Cases / unique collection targets | 100 / 75 |
| Targets with usable evidence | 33 / 75 |
| Cases with usable evidence | 49 / 100 |
| Cases without usable evidence | 51 / 100 |
| Valid final adjudications | 59 / 100 |
| Match / mismatch / uncertain / parked | 2 / 2 / 55 / 0 |
| Incomplete cases | 41 / 100 |
| Labeler attempts / judge attempts | 300 / 61 |
| Distinct subscription-backed sessions | 361 |
| Rejected assessment outputs | 82 |

No pending, running, or quarantined jobs remained in the corrected run; artifact integrity was verified. Terminal accounting is not successful verification coverage. The run ended **partial** because 41 cases lacked a valid final adjudication. Validation failures were not converted into verdicts.

| Evidence availability | Match | Mismatch | Uncertain | Incomplete | Total |
|---|---:|---:|---:|---:|---:|
| Usable evidence | 2 | 2 | 6 | 39 | 49 |
| No usable evidence | 0 | 0 | 49 | 2 | 51 |
| Total | 2 | 2 | 55 | 41 | 100 |

Of 49 evidence-bearing cases, 39 remained incomplete (79.6%). This measures pipeline completion, not semantic accuracy. Of 61 cases with three valid labels, 60 were unanimous and one split two-to-one; consensus does not establish correctness.

### Invocation and usage accounting

The corrected run used 361 distinct Codex sessions authenticated through ChatGPT, with no API-key fallback. Fresh sessions establish context separation, not statistical independence. The requested model lineup was recorded, but actual backend model identity was not independently attested.

| Reported counter | Corrected run |
|---|---:|
| Input tokens | 3,826,630 |
| Cached input tokens | 1,520,128 |
| Output tokens | 138,127 |
| Calls on cases without usable evidence | 204 / 361 |

All 361 usage records were partial. Cached-token inclusion and billing semantics were not established; these counters must not be added or subtracted to invent billable totals. Subscription usage is neither measured API expenditure nor evidence of free, unlimited execution.

The cancelled first run used 101 labeler calls. Together, the two pilot runs consumed 462 calls; this excludes earlier synthetic diagnostics and startup attempts. Per-run caps do not cap cumulative usage across replacement runs. Recorded corrected-run wall time was about 36 minutes 45 seconds, including collection and a manual pause, so it is not a clean inference-throughput benchmark.

## Defects fixed during V0

### Complete HTTP responses incorrectly reported as failures

A response could close its underlying socket after the complete body had been read. Updating the timeout on the next loop iteration then raised a socket error, discarding otherwise usable content. The collector now checks response completion before updating the timeout and closes response resources explicitly.

A synthetic loopback HTTP regression reproduced the failure before the fix. Recollection increased usable targets from 9 to 33 out of the same 75 targets. The implementation marker `collector-v2` identifies this collector revision; it does **not** mean product V2 or replacement-domain discovery.

### Cancelled run reported as running

Finalization previously checked pending work before the cancelled terminal state, allowing an already cancelled run to return `running`. Terminal-state handling was corrected and covered by a failing-then-passing regression.

Recorded verification after both fixes: 39 offline tests passed, along with Ruff lint and format checks. This is the implementation's historical verification record, not evidence of production accuracy or scale.

## Remaining limitations

### Reachability is not usable evidence or company identity

Upstream reachability screening describes availability at an earlier observation time. Pramana assumes reachable inputs and fetches content with robots, TLS, public-destination, media, size, and time constraints; it does not perform live/dead classification. A previously reachable website can therefore yield no usable bundle, and a usable page can still represent another company or a parked domain.

The corrected collection recorded 44 failure events, including secondary-page failures: 24 robots-unavailable, 9 DNS, 4 TLS-validation, 3 crawl-rate deferrals, 2 connection failures, 1 HTTP 403, and 1 unsupported-encoding event. These are event counts, not 44 distinct failed targets; 42 targets had no usable evidence.

The collector conservatively defers redirecting robots files and crawl directives slower than its configured pacing. Robots parsing is not fully standards-compatible. Secondary-page discovery is restricted to the exact final hostname, with no public-suffix-based boundary, HTTP/`www` fallback, or browser rendering. Caller-supplied destination hints can inform future fetching but cannot establish company identity.

### Valid JSON did not guarantee valid evidence citations

Of 82 rejected outputs, 78 contained excerpts not found exactly in the referenced evidence element, 2 referenced unknown elements, and 2 judge outputs omitted required label references. There were 80 rejected labeler outputs and 2 rejected judge outputs; several failures could affect one case.

The current interface asks models to reproduce opaque identifiers and exact excerpts. Ellipses, whitespace changes, or excerpts from another element can fail validation. These failures cannot be assumed semantically correct without review, and weakening grounding checks would hide the problem.

### Input quality and provenance remain imperfect

The source adapter flattens location fields too broadly, allowing duplicated components and literal boolean values into location text. Unknown field independence was conservatively represented as website-derived, which conflates unknown provenance with known website dependence. Structured address mapping and an explicit independent/website-derived/unknown provenance contract remain pending.

### Assessment work was poorly targeted

Cases without usable evidence consumed 204 calls. All 55 accepted uncertain adjudications requested additional collection, but the run explicitly allowed zero supplemental rounds and one attempt per role. The workflow supports bounded supplemental rounds; they were disabled in this experiment. Many empty bundles also lack an approved discovered link, so enabling another round alone would not resolve them.

One labeler queue processes cases in reverse order, delaying convergence on three labels for the same case. Separate contexts provide blindness; different case order is not necessary for independence. Queue-priority alignment remains proposed work.

### Pilot infrastructure is not a production verifier

There is no deterministic production decision engine, dedicated verified-company-domain output contract, production release threshold, hosted service, or demonstrated multi-million-case capacity. SQLite WAL, bounded workers, and durable receipts provide a local pilot foundation. Broader prompt robustness, quota behavior, resource costs, and large-scale recovery still need measurement.

## Agreed V1 scope

These are requirements agreed after V0, **not claims that the current implementation already satisfies them**:

- Assume the caller supplies reachable candidate domains. Reachability screening is an upstream responsibility, not a Pramana feature or pending implementation task. Require no provider-specific status flag or saved probe artifact; do not classify domains as live or dead.
- Allow redirects, including cross-domain redirects, while verifying company identity from evidence.
- Return the correct, evidence-supported company domain when a relationship is verified. Retain the original candidate, resolved destination, verdict, and supporting evidence so the result is auditable.
- A verified domain can be the supplied candidate or an evidence-supported redirect destination. Neither a redirect nor an HTML canonical tag alone proves company identity.
- For unrelated, parked, or unresolved candidates, preserve the appropriate verdict and leave the verified company domain unset. A fetch failure is not an identity mismatch.
- Keep replacement-domain discovery out of V1.

## Proposed next development sequence

1. Implement the verified-domain result contract with explicit provenance for caller-supplied reachable candidates. Correct source address mapping and distinguish unknown field dependence.
2. Improve collection compatibility: bounded robots redirects under the same destination/TLS checks, crawl-delay rescheduling, and optional timestamped caller-supplied destination hints. Preserve collection failures as operational outcomes.
3. Replace model-authored citation copies with short passage selections whose exact excerpts and lineage are attached by the host. Keep semantic grounding validation and require explicit coverage of all three labels by the judge.
4. Define an auditable not-assessed outcome for exhausted empty bundles before changing the current every-case assessment workflow. Keep these cases in end-to-end coverage denominators rather than fabricating agent verdicts.
5. Trial bounded useful supplemental collection and validation repair, with explicit budgets and immutable new rounds. Changed evidence requires three fresh same-round labels. Unknown external execution must not be silently retried.
6. Align case priorities across blind labeler streams and measure time to adjudication.
7. Run a 10–15-case development canary before another 100-case campaign. Include reachable redirecting domains, sparse evidence, identity conflicts, and citation stress cases. Preserve the frozen V0 baseline and keep holdout cases out of tuning.

Progress should be assessed using collection coverage, valid evidence-grounded completion, verified-domain traceability, calls spent without evidence, and complete operational accounting. Report raw counts and denominators. A small targeted independent review can inspect semantic failures; agent agreement alone cannot supply an accuracy claim. No numeric production acceptance threshold is established here.

## Deferred to V2

Replacement-domain discovery starts when the supplied candidate cannot establish the correct company website. V2 may generate and rank alternative candidates and verify identity using the same evidence standards. Reachability screening remains an upstream responsibility; any discovery integration must define that handoff separately. Search strategy, candidate budgets, ambiguity handling, and evaluation require a separate specification. Following an existing candidate's redirects remains within V1.

## Related documents and private evidence

- [Product contract](specs/01-product.md)
- [Evaluation and denominators](specs/05-evaluation.md)
- [Implementation status and recorded verification](implementation.md)
- [Runtime boundaries and measurement gaps](runtime-capabilities.md)

The private experiment directory retains the frozen manifest, both run configurations, case inputs, partition, results audit, and human-readable report. Runtime storage retains immutable bundles and invocation receipts. Those artifacts, rather than the aggregate tables alone, are the basis for reproducing the results; they are intentionally not distributed with the repository.

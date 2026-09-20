# Architecture and implementation plan

Status: proposed implementation sequence. Implementation has not started.

## System boundaries

Pramana verifies company–website relationships independently of consumer applications and data providers. Integrations map authorized external records into the provider-agnostic input contract. The core does not depend on a consumer database, application codebase, or existing liveness service.

The repository contains reusable source code, specifications, and synthetic fixtures. All consumer records and derived runtime artifacts reside in consumer-controlled storage outside the checkout. No implementation step may introduce consumer data into repository history or development collaboration tools.

Model routing, data disclosure, cost budgets, adjudication policy, and production enforcement require explicit configuration before execution. Agent-derived reference labels remain provisional and do not establish production release criteria.

## Proposed module seams

Python is the proposed implementation language; library choices and versions are deferred until implementation discovery.

| Module | Responsibility | Boundary |
|---|---|---|
| `contracts` | Versioned cases, evidence, labels, events | No network or model calls |
| `ingest` | Provider-neutral import and provenance validation | External adapters map into core contracts |
| `collection` | Bounded fetch/redirect policy | Receives URLs and policy; emits fetch artifacts |
| `extraction` | Deterministic evidence extraction | Stored bytes to versioned evidence |
| `artifacts` | Immutable blobs, manifests, receipts | No verdict policy |
| `orchestration` | Scheduling, retries, resume, rounds | Calls collector and runtime adapters |
| `agents` | Runtime capability probe and dispatch | No dependence on a particular subscription/API |
| `validation` | Schema, citation, lineage checks | Distinguishes invalid execution from uncertainty |
| `measurement` | Append-only telemetry and normalization | Preserves usage provenance and missingness |
| `evaluation` | Sampling, splits, comparison metrics | Keeps holdout isolated from rule development |
| `rules` | Deterministic identity assessment, later phase | No inference or network access |
| `reporting` | Reproducible Markdown/JSON reports | Derived from immutable artifacts and events |

Proposed local storage: a private artifact directory for content-addressed blobs and JSON/JSONL records, with a small transactional index for scheduling and resume. Storage technology is an implementation choice; immutable provenance and atomic receipt semantics are requirements. A filesystem alone does not provide transactional multi-worker scheduling.

## Implementation order and likely files

1. **Contracts and synthetic fixtures**: `src/pramana/contracts/`, `tests/fixtures/`, `tests/test_contracts.py`. Define canonical hashes, states, reason codes, and privacy-safe examples.
2. **Deterministic collection and extraction**: `src/pramana/collection/`, `src/pramana/extraction/`, `tests/test_collection.py`, `tests/test_extraction.py`. Implement budgets and destination controls before live website access.
3. **Artifacts and telemetry**: `src/pramana/artifacts/`, `src/pramana/measurement/`, `tests/test_resume.py`, `tests/test_measurement.py`. Integrate from the first collector slice, not after agent runs.
4. **Runtime capability spike**: `src/pramana/agents/`, `docs/runtime-capabilities.md`. Demonstrate fresh contexts, receipts, model identity/usage availability, capacity, cancellation, and operator-assisted limitations using synthetic evidence. Do not assume tools can be invoked unattended from a standalone script.
5. **Three labelers and judge**: `src/pramana/orchestration/`, `src/pramana/validation/`, versioned prompt assets and their tests. Review execution-ready prompts for the selected runtime before any labeling run.
6. **Sampling and reporting**: `src/pramana/evaluation/`, `src/pramana/reporting/`, `tests/test_reporting.py`. Add provider-neutral import, grouped splits, metric reconciliation, and pricing assumptions.
7. **Pilot**: run a small synthetic smoke experiment, then the authorized 100-case sample. Store outputs outside the repository; publish aggregate findings in versioned documentation only after disclosure review.
8. **Deterministic verifier**: `src/pramana/rules/`, `tests/test_rules.py`. Develop on frozen development evidence and evaluate separately on holdout. No production enforcement in this phase.

A minimal CLI can expose import, collect, label, judge, resume, and report operations, but exact command syntax is deferred. Packaging, dependencies, and CI configuration will be proposed during implementation, not silently selected by this document.

## Meaningful verification surfaces

- Fake HTTP/DNS fixtures: redirect loop, private-address redirect, DNS rebinding, oversized/compressed response, slow stream, Retry-After, malformed HTML, and cross-origin credentials.
- Evidence snapshots: same input bytes/configuration yield identical extraction; multilingual names, IDNs, relative links, long pages, and multiple organizations retain auditable evidence.
- Agent contract fixtures: unsupported citations, invalid output, prompt injection text, missing labeler, unanimous incorrect labels overridden by the judge, and supplemental evidence rounds.
- Resume fault injection: process exit around artifact/receipt writes, duplicate completion, failed attempts with incurred usage, and cancellation preserve accurate lineage and cost.
- Cost fixtures: cached tokens included in input, reasoning included in output, partial/missing usage, shared collection, retries, parallel duration, and unknown orchestration costs.
- Dataset fixtures: corporate-family overlap and synthetic pairings cannot leak across development/holdout; incomplete cases remain in end-to-end reporting.

Network tests and model-assisted smoke runs are separate from deterministic offline tests. No claim of quality rests only on schema-valid output.

## Open choices before implementation/pilot

| Choice | Proposed default / evidence needed |
|---|---|
| Agent runtime | Operator-assisted adapter; prove actual capabilities before promising automation |
| Model selection | Record actual model for each role; same model allowed, correlated errors disclosed |
| Company source | Owner-authorized export with field provenance; inspect available identifiers first |
| Relationship policy | Conservative continuity policy from labeling spec; owner decides disputed business semantics |
| Limits and budget | Proposed collection caps; select run wall-time/resource budget before execution |
| Usage availability | Report real counters when available, estimates separately, unknowns explicitly |
| Publication/license | Local/private repository; owner selects distribution terms later |

## Design stress test

- **The source record came from the same website.** Mark dependence and avoid counting it as independent corroboration.
- **Three agents agree on a misleading body mention.** Judge verifies prominent identity and citations; agreement is insufficient.
- **A site redirects to a genuine parent.** Capture relationship evidence and apply the configured policy; do not infer mismatch from the redirect.
- **Usage counters are inaccessible.** Preserve missingness; produce partial and scenario estimates, not fabricated exact costs.
- **Many companies share one website.** Collect once, label each company association, avoid duplicate collection charges.
- **The network changes mid-experiment.** Freeze bundles; new observations create versions and new rounds.
- **The pilot is mostly easy sites.** Report strata and cost scenarios; do not extrapolate representative accuracy or throughput.
- **A labeler crashes after spending tokens.** Retain/reconcile attempt usage; case remains incomplete until three valid labels and adjudication exist.

## Implementation readiness

The specifications define the collection, three-labeler, judge, and measurement experiment. Implementation readiness depends on validating the runtime adapter and consumer data boundary. Runtime capabilities and actual source fields are the main unresolved feasibility inputs. Numeric production accuracy thresholds and paid-provider configuration remain intentionally unset.

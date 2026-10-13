# Implementation status

Date: 2026-09-21. Version: 0.2.0, local pilot refactor.

The repository now contains executable Python software. The end-to-end synthetic workflow is implemented; a Codex subscription adapter has passed a one-case live synthetic probe. An authorized private 100-case pilot on a sample of company records finished with partial results; see [V0 findings](v0-findings.md). The production-scale product is not complete. Specifications remain the intended contract. This document records the implemented subset and its deviations without weakening those requirements.

## Development choices

- Python 3.12+, standard library at runtime, setuptools packaging.
- SQLite WAL with `synchronous=FULL`, foreign keys, a five-second busy timeout, and one executor thread per Store for serialized asynchronous access. Local disk only.
- Four-space indentation, Ruff formatting at 100 columns, Ruff import/undefined-name/basic-error checks, and standard-library unittest. Ruff and build are development extras, not runtime dependencies.
- Synchronous storage methods are for setup or the single writer thread. Concurrent callers must use `await store.call(...)`; a Store connection is not a general-purpose thread-safe database API.
- No hosted service, paid provider, or release threshold was introduced. Pilot data remains in private runtime storage and is not distributed.

The startup check requires SQLite 3.51.3+ or the documented 3.50.7/3.44.6 backport branches. This follows the [SQLite WAL-reset fix documentation](https://www.sqlite.org/wal.html#walresetbug). Python's version alone does not establish its linked SQLite version. Inspect it with `python -c 'import sqlite3; print(sqlite3.sqlite_version)'`.

## Commands

From the checkout, with a patched SQLite runtime:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pramana preflight
.venv/bin/pramana smoke --run smoke-100 --cases 100
.venv/bin/pramana status --run smoke-100
.venv/bin/pramana verify --run smoke-100
.venv/bin/pramana report --run smoke-100
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
```

Without installation, prefix commands with `PYTHONPATH=src` and use `python -m pramana`.

Reports are written under `.local/consumers/synthetic/runs/<run>/reports/`. Repeating the same completed smoke run reuses its immutable results. A changed manifest or configuration requires a new run ID; an intentional replicate also requires a new replicate ID. The synthetic runtime always returns uncertain, explicitly records that no identity assessment occurred, and does not impersonate the configured models.

Use global options before the command:

```sh
pramana --consumer consumer_a config > .local/pilot-config.json
pramana --consumer consumer_a import .local/cases.jsonl --config .local/pilot-config.json --run run_a
pramana --consumer consumer_a collect --run run_a --allow-network
pramana --consumer consumer_a resume --run run_a
```

For subscription-backed labeling, generate configuration with `config --runtime codex-subscription-v1`, then explicitly authorize a run with `--allow-network --allow-codex`. See [runtime capabilities](runtime-capabilities.md) for the live smoke command, limits and measured behavior. Other runtime names are collection-only until an adapter is implemented. The default `synthetic-v1` configuration uses fake collection and accepts only explicitly synthetic cases for execution. Import alone does not send data anywhere.

`resume --retry-unknown` explicitly authorizes another attempt after ambiguous execution; this may repeat an incurred external call. Plain resume leaves those jobs quarantined. `cancel` stops new admissions; in-flight work retains receipts. Interrupting the running process cancels its workers and persists interrupted states where possible. A hard process kill is recovered using lease expiry.

## JSONL case input

One object per line. All values below are synthetic:

```json
{"case_id":"case_1","company":{"company_id":"company_1","name":"Example Workshop","provenance":{"name":{"source":"synthetic_fixture","observed_at":null,"dependence":"independent"}}},"candidate_url":"https://example.test/","source_record_reference":"synthetic_1","stratum":"synthetic","synthetic":true}
```

Optional company fields are `legal_name` (string), and `aliases`, `descriptions`, `locations`, `phones`, `social_urls` (string lists). Every supplied field requires provenance. Source names, source references, sample strata, company IDs, and synthetic flags are excluded from assessor company inputs. Only field values, dependence flags, observation dates, opaque lineage handles, and evidence are exposed. Website evidence itself remains untrusted data; adapters must enforce the execution boundary described in the labeling spec.

## Contract coverage

| Area | Implemented | Remaining work |
|---|---|---|
| Cases and identities | Versioned canonical hashes, provenance validation, immutable manifests, opaque assessor handles | Broader consumer adapter coverage and independent semantic validation |
| Collection | Public-only destinations, per-connection DNS pinning, TLS validation, redirect loops/caps, robots checks, byte/time bounds, bounded concurrency, per-origin spacing, retry caps, durable fetch intent/completion events | Broad live-network validation, full robots standard compatibility, HTTP-date Retry-After handling |
| Extraction | HTML identity fields, visible text, structured organizations, social/phone/address candidates, parking indicators, bounded logo metadata, deterministic IDs and counts | Broader language patterns and corpus-based coverage validation |
| Artifacts | Consumer-scoped private directories, atomic content-addressed publication, body/hash validation | Backup/restore tooling, retention/purge and orphan collection |
| Scheduling | Full collection barrier, independent three-role queues, overlapping judges, fenced leases, heartbeat, backpressure, retries, cancellation, supplemental rounds, explicit unknown-execution retry | Distributed backend, provider rate/token quotas, measured fairness under millions of rows |
| Assessments | Codex subscription adapter and versioned rubric prompt, exact-excerpt citation and lineage checks, anonymized judge inputs, immutable old rounds | Broader prompt evaluation and error-directed validation repair, external reconciliation adapter |
| Measurement | Append-only events, attempt receipts, late usage reconciliation, missingness, inclusive-token pricing helper, production scenario helper | Complete infrastructure/resource telemetry, verified prices, integrated low/base/high production reports |
| Reporting | JSON, JSONL and Markdown, state reconciliation, reference provenance, valid current-round pairwise comparisons, judge diagnostics, usage totals, wall versus aggregate service time | Full stratification, historical round diagnostics, latency distributions and production scenario presentation |
| Evaluation | Reference-agreement denominators and grouped development/holdout splitting utilities | Frozen dataset/access workflow, uncertainty intervals, deterministic rules developed on authorized development evidence |
| Scale | Bounded worker count, paged row admission, indexed queues, streaming imports | Budgeted multi-million-case synthetic capacity and restart campaign, live throughput validation |

## Current limitations against the V1 contract

Secondary-page discovery and its redirects are restricted to the exact final hostname. This is stricter than the specification's registrable-domain boundary and avoids claiming public-suffix support without shipping and versioning that data. No HTTP or `www` fallback is implemented. Collector revision `collector-v3` follows bounded robots redirects and schedules requests under crawl directives within the target budget. Truncated robots content and unaffordable delays defer collection. Older collector policies retain their conservative robots behavior. Retry-After dates are deferred rather than ignored. Unsupported content and collection failures do not become identity mismatches.

Robots parsing currently uses Python's `RobotFileParser`; it is not a complete RFC 9309 implementation. Broader internet collection needs compatibility testing before rollout. Extraction uses the standard-library HTML parser rather than a browser DOM; offsets refer to retained visible-text normalization, with tag locations for other fields. Depth is capped. Logo presence is metadata, never an identity verdict.

Collector version `collector-v2` fixes complete `Connection: close` responses being
misreported as connection failures: response completion is checked before changing
the socket timeout, and response resources are closed explicitly. A synthetic
loopback HTTP regression reproduces the original failure. Recollection uses a new
configuration and run; existing bundles and assessment receipts remain immutable.

SQLite is a pilot backend. Streaming input and bounded workers do not prove multi-million-case capacity: per-case blob fsyncs, manifest initialization, reporting scans and database contention need measurement. The grouped-split helper is explicitly pilot-sized and holds the supplied case set in memory. There is no bulk-run authorization implied by a successful smoke test.

The runtime root is a private filesystem namespace, not an authentication system. Do not share a root with mutually untrusted operating-system users, use symlinked storage, or place runtime data in tracked directories. Never submit credentials in URLs or case fields. URLs and evidence belong only in consumer-controlled artifacts.

## Evidence and next milestones

The offline suite exercises SSRF rejection, rebinding-address rejection, robots blocking, compressed-body limits, redirect loops, secondary-page boundaries, deterministic extraction, malformed/oversized content, independent streams, judge overlap, supplemental rounds, stale completions, late usage, cancellation, cache isolation, corrupt blobs, and incomplete-case denominators.

The [runtime adapter](runtime-capabilities.md) has now supported a private 100-case pilot. Its partial outcome and proposed follow-up sequence are documented in [V0 findings](v0-findings.md): improve source mapping, collection, citations, and verified-domain reporting, then run a smaller development canary before another full pilot. The later deterministic verifier depends on frozen development evidence and separated holdout; this implementation deliberately does not invent assessment rules or production acceptance thresholds.

## Verification recorded for this implementation

- Python 3.12.3 with SQLite 3.51.3 built in an isolated `/tmp/pramana-sqlite` directory; the system SQLite 3.45.1 was not modified.
- `LD_LIBRARY_PATH=/tmp/pramana-sqlite PYTHONPATH=src python3 -m unittest discover -s tests -v`: 30 tests passed.
- Ruff checks and format verification passed; relative Markdown links and `git diff --check` passed.
- Source distribution and wheel built successfully. The source distribution includes synthetic fixtures; neither distribution contains runtime data.
- The installed wheel completed the 100-case offline smoke run: 50 collection targets, 300 synthetic label attempts, 100 synthetic judge attempts, 100 uncertain results and no live calls.
- Repeating the same smoke command preserved one report snapshot (event 1403), 400 total assessor attempts and 50 completed collection jobs.

The `/tmp` runtime is a validation environment, not an installed system dependency. This checkout's commands need a Python linked against a supported SQLite build; while the isolated library remains available here, prefix them with `LD_LIBRARY_PATH=/tmp/pramana-sqlite`. Asyncio executor wakeups were blocked by this session's sandbox, so the offline suite and smoke runs were executed outside that sandbox. Their HTTP/model adapters remained synthetic.

Subscription adapter verification: 37 offline tests passed before the live probe. The successful one-case probe used four distinct Codex sessions with ChatGPT login; the earlier three startup timeouts remain separately accounted for with unknown usage. That synthetic probe sent no real consumer data and configured no API-key fallback. The subsequent authorized pilot is documented separately in [V0 findings](v0-findings.md).

Collector and cancellation regressions: 39 tests passed after reproducing and fixing
the closed-response socket failure and a finalization return value that reported
`running` for an already cancelled run with pending jobs. The socket regression
uses a synthetic loopback HTTP server; neither regression invokes a model.

## Post-V0 contract and workflow refactor

New configurations use `pramana.v2`, `collector-v4`, and, for subscription sessions, `codex-evidence-v3` with `rubric-v2`. These are implementation revisions, not replacement-domain discovery. The canonical hash envelope remains frozen at `pramana.v1` so existing blob identities and manifests remain valid. Explicit legacy configuration and case contracts are still supported; old prompts remain separately available.

- `evidence.py` builds a deterministic passage catalog and reconstructs citations from selected IDs. Exact excerpts and lineage are host-owned; semantic support still requires assessment.
- `workflow.py` decides empty-bundle admission, three-label readiness, and useful supplemental work. `storage.py` applies those decisions transactionally with existing fencing and receipts.
- `results.py` derives versioned case results, preserving subdomains and leaving verified domains unset without an explicit supported match. Operational status is separate from verdict.
- New reports (`v3`) include evidence coverage, verified-domain coverage, not-assessed and failed cases, validation rejections, and calls without usable evidence. `report` exports `cases-<report-version>-<snapshot>.jsonl` alongside the summary, Markdown, and event files in one database snapshot. Exports are private, atomic per file, and reject conflicting existing snapshots.
- New provenance uses `dependence` with `independent`, `website_derived`, or `unknown`. Historical boolean provenance is never silently reinterpreted. Consumer-specific address mapping stays in private adapters.
- Empty bundles consume no assessment calls. New rounds require new extracted evidence; unsuccessful supplemental collection retains the earlier uncertain adjudication and the attempt receipt.

Existing saved results remain historical. Improved code does not turn the V0 pilot into a successful validation campaign. A separately configured development canary and targeted semantic review are still required before any quality claim or larger run.

### Refactor verification recorded on 2026-09-21

- 57 offline tests passed, including reproduced robots redirect/pacing failures, passage reconstruction, canonical-only rejection, verified-domain exports, empty-bundle admission, legacy prompt/configuration compatibility, queue priority, supplemental recovery, and immutable report collision checks.
- Ruff lint and formatting checks passed. Public Markdown links, whitespace, and consumer-specific terminology checks passed.
- Version 0.2.0 source distribution and wheel built successfully. The built wheel completed a 100-case offline smoke run; all cases reconciled with synthetic assessments.
- A separate 10-case development canary completed 6 valid adjudications: 5 provisional matches with verified-domain fields and 1 mismatch. Four cases had no usable evidence and were not assessed. Overall run status remained partial.
- The canary used 24 distinct ChatGPT-authenticated sessions, with zero rejected assessment outputs and zero calls on empty bundles. It was bounded to one attempt per role and at most one supplemental round (80-call ceiling); no supplemental calls were needed.
- Reported counters: 300,036 input, 4,864 cached-input, and 7,335 output tokens. All 24 usage records remained partial; counters do not establish complete billable usage. Wall time was approximately 129 seconds. Actual backend model identity remained unattested.

The canary used development cases only and preserved the frozen V0 artifacts. Different inputs/provenance and the small purposive sample prevent a population-quality or causal improvement claim. Independent semantic accuracy remains unmeasured; collection coverage is still a limitation. No larger live run was performed.

### Stricter match policy

New runs require an explicit second-identifier citation in addition to company identity. The default is `rubric-v2` with `codex-evidence-v3`; `prompt_v2.py` preserves the previous prompt unchanged for historical configurations. Match assessments and per-case results retain the selected supplied value, dependence status, and supporting citation. Unknown phone/address provenance remains disclosed; known website-derived fields and social profiles without independent provenance cannot corroborate.

The host validates the supplied-field reference, cited passage, website, and provenance. Semantic attribute agreement remains the assessors' responsibility. This change does not introduce a deterministic verifier or independently establish accuracy. The earlier canary remains a `rubric-v1` result; no historical artifacts were relabeled.

Verification: 64 offline tests passed, including name-only rejection, phone/address/social selections, provenance restrictions, judge enforcement, prompt/rubric compatibility, and legacy name-only matches. No additional live model calls were made for this policy change.

A subsequent authorized live run applied the stricter rubric to the same 10 development cases: 4 matches (3 supported by supplied phones, 1 by a supplied address), 1 uncertain, 1 mismatch, and 4 not assessed. It used 24 distinct ChatGPT-authenticated sessions, with zero rejected assessment outputs and zero calls on empty evidence. One prior match became uncertain in the new run. Seven unexpired evidence bundles were reused; three targets were recollected. The run remained partial because four cases lacked usable evidence. Source-field dependence remains unknown for the four corroborating identifiers; this is not independent accuracy validation. Detailed results and comparisons remain private.


## Collection budget correction

`collector-v4` separates the shared active network budget from required pacing waits. Robots requests, redirect hops and retries share the configured chain budget; origin delays and Retry-After waits consume the unchanged target deadline. This prevents a crawl delay equal to the chain limit from automatically preventing page collection. Explicit older collector revisions preserve their prior timing behavior and separate cache identities.

The revision adds operational diagnostics for robots/page challenges, empty or script-only HTML, unsupported media and suspected parking shells, plus TLS verifier codes/messages. These do not establish reachability or company identity. JavaScript execution, challenge bypass, TLS relaxation and replacement-domain discovery remain outside this change.

Verification: 70 offline tests passed, including crawl delay equal to the chain limit, legacy timing preservation, shared redirect budgets, retry exhaustion, unaffordable target delays, challenge/script-only diagnostics, and TLS detail preservation. Ruff checks and formatting passed. Live development evidence is stored only in consumer-controlled runtime storage.


## Semantics decision table

The case verdict is now derived from assessor-reported facts rather than copied from the judge's self-reported verdict. `decision.py` (`decision-v1`) is a pure function from one fact set to `(verdict, reason_codes, rule_trace)`: it performs no input/output and makes no model, network or storage calls. `results.py` applies it, records the applied table row, and keeps the assessor's own verdict as `assessor_verdict` with a `verdict_divergence` flag, in the same manner as judge overrides. The governing rule is that a decisive verdict requires positive evidence; absence of evidence yields `uncertain`, never `mismatch`.

New runs default to `rubric-v3`, `codex-evidence-v4`, `evidence-directional-v1` and `decision-v1`, with `pramana.result.v3` records and report `v4`. `codex-evidence-v4` replaces the singular `corroboration` object with `site_substance`, `operator_identity`, a required `relationship.direction` (`evidenced_continuity`, `evidenced_unrelated` or `no_evidence`) whenever the operator differs, and `identifier_findings[]` carrying `agree`, `conflict`, `insufficient_granularity` or `absent` per supplied identifier. `no_evidence` is a first-class value, so "no continuity evidence was found" can no longer be recorded the way "unrelatedness was established" is. `prompt_v3.py` preserves `codex-evidence-v3` unchanged, including its prompt hash; `contracts.SCHEMA` remains frozen at `pramana.v1`, and existing prompts, rubrics and results keep their original interpretation. A changed configuration requires a new run ID.

Two implementation details resolved ambiguities in the approved design. The host-derived website identity is recorded on the assessment as `identity_domain`/`identity_url` and required whenever substance is substantive and the operator is not indeterminate, so a derived match can still publish a verified company domain; `verified_company_domain` is published on the result only when the *derived* verdict is `match`. Identifier agreement remains assessor-reported: the host checks structure, lineage and provenance per finding — an `agree` finding on a known website-derived field is rejected, and a social profile still requires independent provenance — but no phone or address normalization was introduced, and no deterministic identity verifier exists.

This change does not re-score prior runs: assessments produced before `codex-evidence-v4` do not carry the structured facts the table consumes, so the frozen pilot results stand and the next run's verdict distribution is not directly comparable to theirs. It makes the rubric more decisive, converting uncertain cases into decisive verdicts at an error rate no measurement has yet bounded, so a coverage improvement is not evidence of a quality improvement. The design behind it rests on an AI-assisted audit that was not independently human-verified. Establishing an accuracy baseline through independent labels remains separate, still-required work. The specifications under `docs/specs/` describe the derived rubric, the evidence-directional policy and both decision revisions.

Verification: 101 offline tests passed, including one regression per decision-table row, `different_operator` with `no_evidence` yielding `uncertain`, formatted-equivalent phone agreement, city-only versus street-level granularity, explicit former-name continuity with agreeing identifiers, mixed agreement and conflict, placeholder and parked substance, relationship-direction and identifier-finding structural rejections, duplicate findings, provenance restrictions, the frozen `codex-evidence-v3` prompt hash, and derived-verdict results withholding an unverified domain. Ruff checks and formatting passed. A 100-case synthetic smoke run completed with report `v4`: every case derived `uncertain` through `stage1:indeterminate`, zero divergences, and a repeated export was byte-identical.

Two authorized live runs followed. A three-case subscription smoke over synthetic evidence used 12 ChatGPT-authenticated sessions with zero rejected outputs: every judge reported placeholder substance with a cited passage, so all three derived `parked` against an assessor verdict of `uncertain`. That exercises the `parked` path, which no pilot adjudication had ever returned, but the evidence was fixture text and it establishes schema round-tripping, not accuracy.

A live development replay then applied the new revisions to the same ten development records as the earlier strict run, with fresh collection: 7 assessed, 3 not assessed, 0 failed, 0 rejected outputs, 28 sessions, 1 judge override, one two-to-one labeler disagreement, and 4 verified company domains. Derived verdicts were 4 `match` and 3 `uncertain` against assessor verdicts of 5 `match` and 2 `mismatch`, so three cases diverged. All four matches from the earlier strict run reproduced, each now naming an agreeing supplied identifier. One assessor match was withdrawn to `uncertain` because its only location agreement was city-level, recorded as `insufficient_granularity`. Both `different_operator` cases derived `uncertain` through `stage2:different_operator/no_evidence`, including one intended negative that the earlier strict run had called `mismatch`.

That last outcome is the run's material finding: no assessor reported `evidenced_unrelated`, so `mismatch` was unreachable in practice even where both a supplied phone and a supplied address conflicted. The governing principle is behaving as specified, but on this evidence the decisive-mismatch path exists only in theory, and conflicting identifiers currently carry no weight in Stage 2. This is the deliberate rule the design marked for re-examination; one assessed intended negative is an observation, not a measurement. Intended negatives are not truth labels and no independent accuracy baseline was established. Per-case records, URLs and agent input/output remain in consumer-controlled runtime storage.


## Conflicting identifiers as positive evidence

`decision-v2` adds one Stage 2 row to the decision table: a `different_operator` with `no_evidence` of continuity, no agreeing identifier, and counted conflicts on at least two distinct supplied fields derives `mismatch` with trace `stage2:different_operator/conflicting_identifiers`. A conflict counts unless the field is `website_derived`, symmetric with the provenance rule already applied to agreement. One conflict, or two on the same field, still yields `uncertain`; any agreement defers to Stage 3; explicit continuity still short-circuits. The design is recorded in [the conflicting-identifier design](conflicting-identifier-mismatch-2026-09-22.md).

Nothing the assessor emits changes: `codex-evidence-v4`, `rubric-v3` and `evidence-directional-v1` are unchanged, no reason code was added, and the model-facing schema is untouched. `decide` now takes the decision revision explicitly and `case_result` refuses a derived result without one, so exporting an older run can never silently apply a newer table. `decision-v1` runs keep `pramana.result.v3`; `decision-v2` runs produce `pramana.result.v4`. The new default configuration is `decision-v2`.

The rule's effect was measured offline over the seven assessed fact sets committed by the development replay, with no model or network calls: under `decision-v1` they derive 4 `match` and 3 `uncertain`; under `decision-v2`, 4 `match`, 2 `mismatch` and 1 `uncertain`. The only changes are the two `different_operator` cases, each with a cited conflict on both a supplied phone and a supplied address, moving to `mismatch` — exactly the outcome the design stated before the check was run. The intended negative the earlier strict run rejected is rejected again. Re-exporting the committed `decision-v1` replay remained byte-identical. This is a seven-case consistency check on one development set with one assessed intended negative, not an accuracy measurement; the pilot's mismatches cannot be mapped onto this rule, and records supplying a single identifier can never reach `mismatch` under it.

Verification: 108 offline tests passed, including two-field conflicts reaching `mismatch`, one conflict and same-field conflicts staying `uncertain`, website-derived conflicts not counting, agreement deferring to Stage 3, continuity short-circuiting, `decision-v1` behavior preserved and identical across revisions on every other row, an unnamed decision revision rejected, and configuration pairing across both revisions. Ruff checks and formatting passed. A 30-case synthetic smoke on the new default produced report `v4` and `pramana.result.v4` records with zero divergences. No live calls were made for this change.


## Independent reference labels

Independently produced labels can now be recorded and reported. `contracts.validate_reference_label` accepts exactly `case_id`, `verdict`, `reviewer`, `origin`, `blind`, `rationale` and `recorded`; `Store.import_reference_labels` appends them as content-addressed artifacts behind rows keyed `(run, case_id, reviewer, sequence)`, guarded by an immutability trigger and covered by `store.verify`. Import is idempotent by content — a byte-identical record is counted as a duplicate rather than appended — and every accepted record writes an event, so the run's snapshot advances and a later export lands in a new file instead of conflicting with a published one. A reviewer who changes their mind adds a sequence; nothing is overwritten. The CLI subcommand is `reference-import`.

`recorded` is the time the reviewer produced the label and is required from the importer. An import-time stamp was implemented first and removed: it made content-based idempotency impossible and described the import rather than the review, which would have made the blindness check meaningless.

Reporting gains a `reference_agreement` block from the existing `evaluation.reference_metrics`, and `report_version` becomes `v5` only when that block is present, so earlier exports stay byte-identical. The baseline is restricted to blind `independent_human` labels: `owner_review` and sighted labels are recorded and counted separately, `reference_origin` becomes `independent_human` only when the baseline is non-empty, labels for cases without a derived verdict are reported separately and excluded from the matrix, and the block reports how many blind labels were recorded after the run ended. Intended negatives are not admissible as reference labels.

This builds the instrument and not the measurement. No blind label exists for any run, so no accuracy baseline is established and every rate in the block is `null` until one is produced. Blindness remains a declaration the system cannot verify; the guarantee is that sighted and after-the-fact labels are visibly separated. One reviewer is a human judgment from the same evidence, not ground truth.

Verification: 117 offline tests passed, including contract rejection of unknown verdicts and origins, non-boolean blindness, a blind owner review, empty reviewer or rationale, an out-of-run case, a missing or malformed recording time, append-and-supersede sequencing, content idempotency, row immutability, artifact integrity, report version held at `v4` without labels, baseline restriction to blind independent labels, separation of labels for unassessed cases, and reproducible export alongside the earlier version. Ruff checks and formatting passed. The CLI path was exercised on the committed development replay with two `owner_review` labels: both were recorded, the baseline stayed empty with null rates, `reference_origin` stayed `agent_adjudicated`, a repeated import reported two duplicates and zero accepted, the earlier `v4` export remained on disk beside the new `v5`, and artifact integrity passed. No live network or model calls were made.


## Blind review packets

`review.py` (`review-packet-v1`) writes the packets a reviewer needs in order to label a case without being told the answer, exposed as the `review-packet` CLI subcommand. Each packet carries the case ID, candidate URL, bundle ID, the blinded supplied fields with their provenance limitations, the frozen passage catalog the assessors read, and the rubric's verdict definitions. It withholds the verdict, reason codes, assessor and judge output, derived results, the sampling stratum, the synthetic flag, the partition and the source record reference, and lists those withheld names so a reviewer knows what they are not being shown. Packet order is a recorded-seed shuffle, so position cannot hint at how cases were sampled. A `labels-template.jsonl` is written alongside, pre-filled with `origin: independent_human` and `blind: true`; its placeholder verdict and timestamp fail validation until replaced, so an unedited template cannot be imported.

Packets are written from a run's current-round bundles, which exist after `collect` and before any assessor runs. That ordering is the point: a label recorded while no verdict exists is blind by construction rather than by declaration, and the report's count of blind labels recorded after the run ended then corroborates the claim instead of resting on it. Packets stay under the run's Git-ignored runtime directory.

The instrument is complete and the measurement is still absent. Of 147 distinct development-partition source records in consumer storage, 94 already carry a completed verdict and 16 have usable evidence with no verdict in any run; those 16 are the only records in storage that anyone who has read the existing reports could still label blind. Separately, 16 holdout records already carry completed verdicts, so that partition is partly consumed and `05-evaluation`'s holdout isolation should be reviewed before it is relied on.

Verification: 121 offline tests passed, including packet key sets, withheld-field absence, evidence presence, the seeded non-alphabetical ordering and its stability, packets written while no label exists, and an unedited template failing validation while a completed one imports. Ruff checks and formatting passed. The subcommand was exercised on the committed development replay, writing 7 packets over 57 passages with no verdict present. No live network or model calls were made.


## Evidence scope on reference labels

`evidence_scope` is now required on every reference label: `packet` when the reviewer judged the frozen bundle alone, `open_web` when they consulted any outside source. The report computes each scope's confusion matrix and rates separately under `reference_agreement.scopes` and never pools them, because a packet-scoped disagreement indicates an assessment error while an open-web disagreement may instead indicate insufficient collection. `report_version` for a report carrying the block moves from `v5` to `v6`, since the block's shape changed. The column is additive: labels recorded before the field existed keep a null scope, are counted as `unscoped_legacy`, and enter neither baseline rather than being assigned a scope they never declared. The review-packet template declares `packet` and its verdict guide tells the reviewer to record `open_web` instead if they consult anything else.

This was added because the distinction was silently missing: an open-web review would have been counted as a packet-bounded one, attributing a collection limit to the rubric.

A blindness limitation was also found and recorded rather than only in code: a packet withholds the sampling stratum, but summarising many cases together can reveal it anyway. Listing company and candidate-domain pairs across a case set exposed that two cases shared one website, which identifies a constructed pairing. The specification now states that blindness constrains how a case set may be summarised, not only what a packet contains, and the affected development records can no longer be labelled blind by anyone who saw that summary.

Verification: 121 offline tests passed, including rejection of an unknown or null scope, scoped baselines kept separate with their own matrices and rates, scope counts including `unscoped_legacy`, report version `v6`, and the packet template declaring `packet`. Ruff checks and formatting passed. The additive migration was exercised against the existing consumer database holding two pre-scope labels: the column was added, both rows kept a null scope, they were counted as `unscoped_legacy`, both baselines stayed empty, and the re-export landed at `v6`. No live network or model calls were made.

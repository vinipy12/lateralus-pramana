# Asynchronous scheduling and scale

Status: required execution model. Initial pilot: 100 cases. Scale target: 4M+ company–domain cases through collection, three independent labels per case, and adjudication.

## Phase A: collect the full dataset

Freeze the input manifest, deduplicate collection targets within the consumer, and fetch/extract asynchronously with bounded concurrency and per-origin limits. Persist each target's outcome as it completes; never retain the whole dataset or its evidence in memory.

A durable dataset barrier opens only when every target in the frozen manifest has a terminal initial collection outcome. Terminal means a valid evidence bundle, an exhausted collection failure, or an explicit exclusion/cancellation with reason. Timeouts are accounted-for failures, not an excuse for an infinite barrier. Cancellation of the run stops it rather than silently releasing labeling.

A terminal network failure may produce a valid bundle describing unavailable evidence, allowing uncertain labels. An internal corruption or missing bundle blocks the affected cases as incomplete. Neither is silently removed from coverage denominators. Record barrier totals and an immutable release receipt before admitting any initial label work.

## Phase B: three concurrent labeler streams

Activate `labeler_1`, `labeler_2`, and `labeler_3` together after the barrier. Every role traverses the complete case manifest, producing one valid label per eligible case and evidence round. Cases unavailable due to recorded failures remain accounted for as blocked; a stream cannot claim successful coverage while they are unresolved.

The streams progress independently: labeler 1 can process row A while labeler 2 processes row B and labeler 3 processes row C. They need neither identical ordering nor a per-row rendezvous before taking the next row. Use a deterministic recorded order per stream, with fair prioritization of rows near judge-readiness to avoid starving adjudication.

A stream is a durable logical role, not one indefinitely growing agent conversation. Its async workers claim bounded row jobs and use isolated per-row contexts. Worker replacement or sharding preserves role identity and uniqueness. A role remains active until its manifest is exhausted and its work is completed or explicitly failed; supplemental rounds may enqueue additional work for that role. Global completion waits for these rounds too.

## Phase C: judges overlap with labelers

On each accepted label, transactionally check whether the row has valid committed labels from all three distinct roles for the same case, company snapshot, bundle, rubric, policy, and round. Retries from one role cannot satisfy another role. Once ready, enqueue one logical judge job using a unique readiness key in that same transaction.

Judge workers consume ready rows immediately subject to concurrency and rate limits; they do not wait for any labeler stream to finish. Multiple rows may be judged concurrently. The singular judge role describes adjudication semantics, not a single globally serial worker.

```text
all targets -> bounded async collection -> durable dataset barrier
                                               |
                         +---------------------+---------------------+
                         |                     |                     |
                    labeler 1             labeler 2             labeler 3
                    all rows              all rows              all rows
                         +---------------------+---------------------+
                                               |
                               per-row three-role readiness
                                               |
                                 bounded async judge workers
                                               |
                                    persisted adjudications
```

If a judge requests supplemental evidence, collect only that row's additional evidence within policy, freeze a new bundle, and enqueue all three roles for the new round. It does not reopen the global initial collection barrier or stall unrelated rows. The next judge waits for the three labels of that new round only.

## Async execution and backpressure

Use async I/O for website requests, runtime calls where supported, and queue waiting. Run blocking adapters/database work and CPU-heavy extraction through bounded executors so they cannot block the scheduling loop. Stream manifests and use indexed cursor pagination; never allocate one coroutine or load one payload per dataset row up front.

Separate concurrency settings for collection, each labeler role, judging, and supplemental collection. Reserve judge capacity so labeler traffic cannot consume every execution slot. The runtime adapter must support three concurrently progressing labeler streams and overlapping judge work; a constrained interactive session is not the production architecture. Preflight reports effective capacity and rejects unsupported execution settings instead of silently switching to dataset-serial judging.

Use bounded in-memory queues backed by durable jobs. Configure request/token limits, queue high-water marks, retry budgets, and consumer/resource caps in the manifest. When judging falls behind, slow label admission and prioritize missing labels for already-started rows. Backpressure must not prevent the third label needed to drain the judge backlog. Do not slow a role solely because its independent cursor differs from others.

An exhausted row retry budget does not stop unrelated rows. An unresolved external invocation remains quarantined as execution-unknown until reconciled or explicitly retried; it does not count toward readiness. Cancellation stops admissions, records in-flight attempts, and preserves resumable state.

## Scale and storage

SQLite remains the single-host pilot backend. Durable queue/state interfaces must permit a different transactional backend and shared artifact store without changing work keys, role semantics, evidence contracts, or metrics. Do not share a SQLite WAL file across hosts. Choose a distributed backend only when capacity testing demonstrates the need; no distributed storage is implemented by these specs.

At 4M cases, the initial full-label pass contains 12M logical labels and 4M logical adjudications, before retries and supplemental rounds. Execution overhead depends on runtime batching, but row-level independence, result identity, and usage accounting must survive batching. Agent capacity and cost must be measured explicitly; a small pilot or subscription entitlement is not evidence of this throughput.

The deterministic-only verifier remains a separate supported production scenario. It does not replace the scale requirement for the full labeling pipeline.

## Acceptance and capacity evidence

- No initial label is dispatched before the full-dataset collection barrier is persisted.
- All three streams overlap, can process different rows, and cover every eligible row exactly once per logical role/round despite retries.
- A ready row is judged while other rows are still being labeled; multiple judge jobs overlap when configured capacity permits.
- Duplicate label delivery and crashes at readiness creation do not lose or duplicate a logical judge job. Recovery scans indexed unadjudicated-ready work in bounded pages.
- Slow/failing rows, queue saturation, and supplemental collection do not cause a global label/judge barrier or unbounded memory growth.
- A synthetic 4M+ case scheduling test uses fake collection/model adapters, realistic metadata/payload-size distributions, and failure injection. It measures RAM, disk, database contention, queue lag, and restart/reconciliation behavior without paid model calls.
- The live pilot measures collection/label/judge throughput, latency and usage. Project 4M+ runtime/storage/cost with declared capacity and failure assumptions; validate runtime-adapter capacity separately.

Record the hardware, configured concurrency, memory/disk ceilings, and target completion window before capacity tests. No fixed completion SLA is claimed until these are chosen and measured. Passing a fake-adapter load test proves scheduling behavior only; production success requires the full target workload with reconciled results and resource usage.

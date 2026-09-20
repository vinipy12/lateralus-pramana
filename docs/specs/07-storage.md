# Local storage, caching, and idempotent runs

Status: V1 design. Related: [collection](02-collection.md), [labeling](03-labeling.md), [measurement](04-measurement.md).

## Storage layout

Default runtime root: `.local/` inside the project checkout, excluded from Git as a whole. An explicit runtime-root setting may place it elsewhere. An ignored folder is a source-control boundary, not an authorization or encryption mechanism. Consumer data must never enter tracked files, commits, issues, or pull requests.

```text
.local/
  consumers/<opaque-consumer-id>/
    state.sqlite3
    blobs/<content-hash>
    runs/<experiment-id>/
      manifest.json
      reports/
    tmp/
```

Each consumer has a separate database and artifact namespace. Do not share caches or results across consumers. Use private filesystem permissions. Database sidecars, logs, source imports, exports, and temporary artifacts belong under this ignored root too. No real data or database is shipped with the repository. Setup creates empty directories; runtime creates the database after the consumer is selected.

## SQLite responsibilities

SQLite indexes immutable artifact references, cache entries, experiments, cases, logical jobs, attempts, leases, accepted results, and usage events. Large response bodies and evidence payloads remain content-addressed files. Schema versions and explicit migrations are recorded.

Use WAL on local disk, short transactions, foreign keys, bounded busy waits, and a serialized writer queue. Do not hold database transactions while fetching websites or invoking agents. WAL allows concurrent readers but still has one writer and requires processes on the same host; network filesystems are unsupported for this configuration. See [SQLite WAL documentation](https://www.sqlite.org/wal.html).

Record the SQLite runtime version and require a supported patched release at implementation time. Use a durability setting appropriate to retained receipts (`synchronous=FULL` for V1), monitor checkpoint progress and database/WAL size, and handle full-disk or integrity failures explicitly. Back up the database consistently with its referenced blobs; copying a live database file alone is not the backup protocol.

Enforce one accepted result per logical work key with UNIQUE constraints. Use conflict-aware inserts/updates for mutable scheduling state; never replace immutable labels, attempts, or usage records. [SQLite UPSERT](https://www.sqlite.org/lang_upsert.html) handles uniqueness conflicts; it does not make external calls exactly once.

## Work identity

Use canonical, versioned serialization and collision-resistant hashes. All keys include consumer scope.

| Work | Semantic key inputs |
|---|---|
| Collection | Normalized requested target, fetch-policy version, collection generation |
| Extraction | Body hash, parser/normalization versions, extraction configuration |
| Label | Case/company snapshot hash, bundle ID, rubric and relationship-policy versions, prompt version, model/configuration, labeler role, evaluation replicate ID |
| Judge | Ordered/anonymized label-set hash, bundle/company hashes, rubric/policy/prompt/model configuration, replicate ID |
| Rule evaluation | Case/company hash, bundle ID, rule version/configuration |
| Report | Experiment ID, terminal event snapshot, report version, pricing/assumption version |

The three labeler roles always have different keys. A resume preserves replicate IDs; an intentional repeated assessment uses a new replicate ID. Include all behavior-affecting configuration, not only a display model name. If runtime model identity is opaque, limit reuse to that recorded run; do not silently reuse across potentially changed runtime configurations.

## Cache freshness versus resume

Cache lookup uses target and fetch-policy identity within the consumer. Each successful acquisition has a generation, observed time, expiry, and immutable artifact references. Fresh entries may be attached to a new experiment, with reuse events recorded. TTL is a lookup policy, not a mutation of stored evidence.

Resuming an existing run reuses its pinned completed bundles even after the normal cache TTL expires. Explicit refresh, an expired cache used by a new run, or a changed collection policy schedules a new generation. Different collection limits invalidate compatibility unless reuse is explicitly proven by a versioned rule; V1 defaults to a miss.

Extraction may be recomputed from retained bodies without network calls when only extraction configuration changes. Do not cache transient failures as successful evidence. Store failures and next eligible retry times; bounded negative-cache entries may suppress immediate repeats but must expire. Preserve every attempt and its cost.

## Scheduling and crash recovery

1. Insert/find the logical job using its unique key. A completed valid job returns its existing result and emits a reuse event.
2. Claim eligible work in a short transaction with owner ID, expiry, and incrementing fencing token. Only the current token may accept completion; an expired worker cannot overwrite its successor.
3. Persist attempt intent before starting external work; record external invocation IDs as soon as available.
4. Write artifacts to temporary files, flush, validate hashes, then atomically publish on the same filesystem. Commit the accepted result, artifact references, completion state, and terminal telemetry event in one SQLite transaction after artifacts are durable.
5. Export JSONL/report views from committed events. They are derived exports; the append-only SQLite event table is the audit source, avoiding an unsafe database-plus-JSONL dual write.
6. Recovery validates references and identifies unreferenced blobs. Missing/corrupt artifacts invalidate reuse; never silently report a complete job with missing evidence. Garbage collection retains artifacts referenced by pinned runs.

Leases need renewal for long jobs. Before reclaiming an agent job, reconcile its external invocation when the runtime permits. If execution may have occurred but cannot be reconciled, record `execution_unknown`; do not automatically redispatch that job. An explicitly selected retry creates a new attempt and preserves unknown prior usage. Network requests can still be repeated after crashes; every known attempt remains accountable.

## Idempotency contract

- Repeating import of the same scoped source snapshot does not duplicate cases.
- Resuming the same completed run creates no new fetches, labels, or judge calls.
- Repeated completion delivery creates one accepted result and does not double-count an invocation's usage.
- Independent executions and intentional replicates remain distinct and each incur their actual usage.
- Refreshing evidence creates a new generation and dependent work, preserving history.
- Rebuilding a report from the same event snapshot and assumptions reproduces the same totals; reuse does not charge original collection or agent costs again.

These are durable-state and resume guarantees, not a promise of exactly-once external execution. Model outputs and live website responses are not inherently deterministic.

## Verification

Use fault injection around job claim, artifact publication, completion commit, and event export. Exercise concurrent duplicate claims, stale lease completion, expired cache versus pinned resume, model/policy changes, corrupt blobs, interrupted agent calls, and repeat report generation. Assert both result uniqueness and cost conservation. Track cache hit/miss reasons, reused job counts, lease contention, database wait time, WAL size, and reconciliation outcomes.

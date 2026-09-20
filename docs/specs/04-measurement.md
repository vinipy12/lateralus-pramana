# Measurement and production cost estimates

Status: proposed telemetry contract. All metrics have units, scope, provenance, and missingness.

## Event envelope

Every event records `schema_version`, event ID, experiment ID, case ID when applicable, collection target ID when applicable, stage, logical work ID, attempt ID, parent event ID, UTC timestamps, monotonic duration in milliseconds, outcome, configuration hash, and software revision. Shared collection events need not have a single case ID: the case-to-bundle table preserves the relationship.

Use UTC for correlation and monotonic clocks for durations. Record queue time separately from service time. An append-only SQLite event table is the audit source; JSONL exports and aggregates are derived and regenerable. Completion state and its terminal event are committed together; see [storage](07-storage.md).

## Required measurements

| Scope | Fields |
|---|---|
| Experiment | Start/end, elapsed wall time, requested/validated/completed/incomplete cases, targets, concurrency configuration, peak active workers, cancellation |
| Fetch attempt | Queue/service duration, DNS/connect/TLS/first-byte timings when exposed, status, hop count and ordered chain, network bytes observed, decoded body bytes, retry/backoff, cache disposition, failure category |
| Extraction | Duration, page/media type, input bytes, examined/retained/dropped element counts by type, retained characters, truncation, parser failures, logo candidates by source type |
| Agent invocation | Role, model/provider/version when exposed, runtime, invocation/attempt IDs, round, start/end/duration, rubric/prompt hash, evidence hash, outcome, repair reason, usage |
| Resources | Process CPU seconds, peak RSS bytes, stored artifact bytes, sampling method and scope |
| Assessment | Verdict distribution, valid-label count, agreement pattern, judge override, additional-evidence request, uncertain/incomplete rate |

Do not pretend unavailable network phase timings or wire-byte counts were measured. Record `null` and a reason. Decoded body bytes differ from transferred bytes. Shared-process peak memory is run-level unless reliable worker attribution exists; never sum RSS peaks as total memory use.

## Token usage contract

Each invocation has `usage_status` (`reported`, `estimated`, `unavailable`, or `partial`), usage source/runtime version, and nullable fields:

- Total input tokens, cached input tokens, output tokens, reasoning tokens, and provider-reported total tokens.
- Provider-native usage payload reference and documented counter semantics, including whether reasoning is included in output and cached tokens are included in input.
- Missing reason and tokenizer estimates, if any, stored separately from reported counters with tokenizer/version and scope.

Agent input includes rubric, case data, evidence, and runtime-added context when reported by the runtime. Judge input also includes all labeler outputs. Count repair attempts, supplemental rounds, cancelled/failed executions with known usage, and separately measured orchestration model work. If orchestration usage is unavailable, the experiment's complete model cost is unknown even when child usage is available.

Do not scrape or infer secret runtime internals to manufacture billing precision. Local visible-text tokenization excludes hidden context and is an estimate. Preserve raw provider usage without assuming all providers count cached or reasoning tokens identically. Avoid double counting input caches or reasoning included in output.

Report sums of known usage alongside invocation counts by usage status and measured-usage coverage. An invocation with missing usage contributes unknown, never zero, to complete cost.

## Price and cost records

A price table is a dated, versioned input with provider/model, currency, input/cached/output rates, counter semantics, source URL, and effective date. Populate and verify it when estimating a run, not with guessed prices in this specification.

Where total input includes cached input and output includes all billable reasoning:

`model_cost = ((input - cached_input) * input_rate + cached_input * cached_rate + output * output_rate) / 1_000_000`

Use a provider-specific mapping otherwise. Unknown token components produce unknown costs or explicitly bounded estimates, not an exact total. Track actual billed cost separately when available; an API-equivalent calculation is not a subscription invoice or proof that equivalent usage is available through a subscription.

Infrastructure assumptions include compute-hour rates, storage GB-month rates, egress rates if relevant, artifact retention, and worker utilization. Local-machine resource measurements do not directly equal a cloud invoice. Tag estimates with all rates, their units, and their provenance.

## Production scenarios

1. **Experiment**: collection + all labeler/judge/repair/supplemental executions + orchestration + storage.
2. **Deterministic production**: collection + extraction + rules + storage + retries; model cost is zero by design.
3. **Full agent pipeline**: complete collection followed by three labels and one adjudication per case; include retries, supplemental rounds, orchestration, and storage. At 4M rows the initial pass is 12M logical labels plus 4M logical judge assessments.
4. **Hybrid production**: deterministic production + explicitly selected agent review, including all three labelers and judge if that remains the review policy.

Let `D` be unique collection targets, `C` company–domain cases, `h` valid collection-cache hit fraction, and `q` fraction of cases selected for agent review:

`deterministic_total ~= D * ((1-h) * collection_cost + h * cache_read_cost) + C * rule_cost + storage_cost`

`hybrid_total ~= deterministic_total + C * q * agent_review_cost`

Per-unit costs must consistently include retries and specify whether extraction is already included. Shared domain collection is counted once; per-case allocated cost is explanatory, not an additional expense. Refresh cadence, growth, and evidence retention affect recurring costs.

Report low/base/high assumptions for cache hit rate, retry/failure mix, review fraction, and throughput. Weighted estimates require a known production stratum distribution; otherwise show scenarios and do not claim a representative fleet estimate. A 100-case pilot cannot establish production tail behavior or reliable fleet p95.

## Reports

Produce machine-readable events and summaries plus a Markdown report with:

- Totals, median and observed p95 with sample size; omit undefined statistics.
- Wall time versus aggregate worker/agent service time, throughput, queue/backoff time, and measured concurrency.
- Per unique domain and per case costs; cost per 1,000 with denominators explicitly named.
- Separate cold-cache/warm-cache and ordinary/redirected/blocked/failed groups.
- Three-way agreement, judge override, uncertain/incomplete rates, provenance mix, usage coverage, and reference-label limitations.
- Separate spend already incurred, API-equivalent cost, and modeled production costs.
- Reconciliation of events to attempts, attempts to cases, and all published totals.

## Scheduling and scale telemetry

Record collection-barrier time and totals, per-role throughput and remaining rows, judge-ready timestamp, ready-to-dispatch latency, label/judge overlap, active workers, queue depth and oldest-job age, backpressure duration, database contention, and recovery time. Distinguish startup phase duration from steady-state throughput. Estimate full-pipeline wall time as collection-phase duration plus measured overlapped labeling/judging duration; do not sum all agent service times. Include evidence age at labeling after the full-dataset collection barrier. Report the slowest role and judge capacity as potential bottlenecks, with resource assumptions for the 4M+ target.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Runtime prerequisite: patched SQLite

`Store.__init__` refuses to open a database unless the linked SQLite is >= 3.51.3 (or the 3.50.7 / 3.44.6 backports), because of the WAL-reset bug. Many system libraries are older (Ubuntu 24.04 ships 3.45.1), so **every command that touches the store must be prefixed with `LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib`**. That directory is a local build from the sqlite.org amalgamation (see README "Requirements"), not an installed dependency; if it is missing, rebuild it before concluding the code is broken. Check with `python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'`.

## Commands

```sh
# Full offline suite (121 tests, no network, no model calls)
LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m unittest discover -s tests -v
# One test
LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m unittest tests.test_workflow.SupplementalTests.test_supplemental_target -v
# Lint / format (ruff is a dev extra, line length 100)
ruff check src tests && ruff format --check src tests
# End-to-end synthetic workflow
LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m pramana smoke --run smoke-100 --cases 100
LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m pramana report --run smoke-100
```

Python 3.12+, standard library only at runtime. CI (`.github/workflows/tests.yml`) builds SQLite from source and runs the offline suite plus Ruff. There is no pytest and no formatter besides ruff.

## Architecture

The pipeline is a durable job queue, not a task-per-case fanout.

- `cli.py` parses a subcommand, opens a `Store`, and hands a `(store, collector, runtime)` triple to `Pipeline`. Collector and runtime are the only seams that touch the outside world: `SyntheticCollector`/`Collector`, `SyntheticRuntime`/`CodexRuntime`.
- `storage.py` (`Store`) owns one SQLite connection and one worker thread. Synchronous methods are for setup or that thread only; async callers go through `await store.call("method", ...)`, which dispatches onto the single executor. Tables: `runs, cases, jobs, targets, rounds, labels, attempts, receipts, reconciliations, events, cache`. Progression happens inside `BEGIN IMMEDIATE` transactions with fenced leases.
- `orchestration.py` (`Pipeline`) runs a bounded pool of workers per role that claim/renew/complete jobs. Collection runs to completion first, then `release_barrier` opens the three labeler roles, `judge`, and `supplemental`. Every terminal path writes a receipt; the failure outcome distinguishes `invalid_output`, `execution_unknown` (an external effect may have happened — never auto-retried) and `interrupted`.
- `workflow.py` is pure progression policy (empty-bundle admission, judge readiness, supplemental target selection). `storage.py` applies its decisions. Keep decisions here and persistence there.
- `evidence.py` builds the deterministic passage catalog; assessors cite passage IDs and the host reconstructs excerpts, so exact quotes and lineage stay host-owned. `validation.py` checks structure, citations and lineage — never semantic truth.
- `results.py` derives versioned per-case results (including verified domain) from immutable assessments; `reporting.py` exports a report plus `cases-<version>-<snapshot>.jsonl` from one committed DB snapshot.
- `artifacts.py` is content-addressed immutable blob storage under the consumer root; `measurement.py` normalizes usage and cost; `evaluation.py` holds agreement metrics and grouped splits.

## Invariants to preserve

- `contracts.SCHEMA = "pramana.v1"` is the frozen canonical hash envelope — changing it invalidates every existing blob identity and manifest. Behavior changes go into `CURRENT_SCHEMA` (`pramana.v2`), a new `collection.version` (`collector-v4`), a new prompt module, or a new `rubric_version`. Old revisions keep their old behavior and cache identity; `legacy_prompt.py` / `prompt_v2.py` exist for exactly that reason.
- `validate_config` requires a config to contain exactly the `default_config()` keys. A new knob means updating both, and a changed config requires a new run ID — results and report snapshots are immutable, and re-exporting over a conflicting snapshot is rejected.
- Live effects are opt-in per invocation: `--allow-network` for website requests, `--allow-codex` for subscription-backed assessors. The CLI also refuses to run synthetic assessors over any case not explicitly marked `synthetic: true`.
- Everything consumer-specific — case records, URLs, captured pages, evidence bundles, agent I/O, reports — stays under the Git-ignored `.local/`. Fixtures and examples in tracked files must be synthetic; anonymized real records are not acceptable fixtures.
- The collector is the security boundary: public destinations only, per-connection DNS pinning, TLS validation, robots checks, byte/time/redirect budgets. Treat changes there as security-relevant and keep the offline regressions (SSRF, rebinding, robots, compressed-body limits, redirect loops) passing.

## Documentation map

`docs/specs/01-product.md` … `08-scheduling.md` are the contract and remain authoritative over the code. `docs/implementation.md` records the implemented subset, its deviations, and verification runs. `docs/v0-findings.md` and `docs/checkpoint-2026-09-22.md` hold pilot results and next steps. `CONTEXT.md` fixes the vocabulary — use "case", "evidence bundle", "reference label", "not assessed", "verified company domain", and avoid "ground truth" / "gold label". When implementation behavior changes, update `docs/implementation.md` in the same change.

Commit subjects are imperative and prefixed (`docs: …`); keep changes focused.

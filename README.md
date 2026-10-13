# Lateralus Pramana

Evidence-based verification of company–website relationships.

**Status:** experimental local pilot (v0.2.0). The full workflow runs offline with synthetic adapters and has been exercised against live websites and subscription-backed Codex sessions in a small private pilot. It is not a production verifier, and large-scale capacity has not been demonstrated.

Callers supply reachable candidate domains. Reachability screening belongs upstream; Pramana collects page evidence and verifies company identity, including across redirects.

Pramana collects website evidence deterministically, obtains three independent agent labels, and asks a judge to adjudicate every evidence-bearing case. Cases without usable evidence are recorded as not assessed. Case verdicts are derived from the assessments by a versioned decision table, and independent reference labels can be recorded to measure agreement. The resulting reference dataset supports development of a deterministic verifier. The pipeline is designed for multi-million-row workloads through asynchronous collection, three concurrent labeler streams, and per-row adjudication.

## What is implemented

The Python package implements versioned contracts, bounded collection and extraction, immutable content-addressed artifacts, durable three-labeler/judge scheduling on SQLite, structural and citation validation, derived per-case results, and reports. A Codex CLI adapter can launch real labeler and judge sessions through an existing ChatGPT subscription. A pilot on a sample of company records finished with partial results; see [V0 findings](docs/v0-findings.md) and the [2026-09-22 checkpoint](docs/checkpoint-2026-09-22.md). No dataset is distributed with this repository.

See [implementation status](docs/implementation.md) for contract coverage and remaining work, and [runtime capabilities](docs/runtime-capabilities.md) for the live-adapter boundary.

## Requirements

- Python 3.12+. No third-party runtime dependencies.
- **A SQLite library with the WAL-reset fix**: 3.51.3 or newer, or the patched 3.50.7 / 3.44.6 backports. The store refuses to open a database otherwise. Many distributions still ship an older SQLite (Ubuntu 24.04 ships 3.45.1).

Check what your Python is linked against:

```sh
python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

If it is too old, build SQLite from the official amalgamation and point the dynamic loader at it. Nothing is installed system-wide:

```sh
curl -fLO https://sqlite.org/2026/sqlite-autoconf-3540000.tar.gz
tar xzf sqlite-autoconf-3540000.tar.gz
cd sqlite-autoconf-3540000
./configure --prefix="$HOME/.local/pramana-sqlite"
make -j"$(nproc)" && make install
cd ..

export LD_LIBRARY_PATH="$HOME/.local/pramana-sqlite/lib"
python3 -c 'import sqlite3; print(sqlite3.sqlite_version)'   # 3.54.0
```

Any newer release from [sqlite.org/download](https://sqlite.org/download.html) also works. This works on Linux with a CPython that links `libsqlite3` dynamically (the usual case for distribution and `pyenv` builds). On macOS, `DYLD_LIBRARY_PATH` is ignored by the system Python; use a Python built against a recent SQLite (for example Homebrew's) instead.

## Quick start

With the patched SQLite on `LD_LIBRARY_PATH`, from the checkout:

```sh
PYTHONPATH=src python3 -m pramana preflight
PYTHONPATH=src python3 -m pramana smoke --run smoke-100 --cases 100
PYTHONPATH=src python3 -m pramana report --run smoke-100
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The offline suite (121 tests) and the smoke run make no website or model calls. Smoke reports and receipts are written under `.local/consumers/synthetic/`. Synthetic verdicts exercise the workflow and are not reference labels for assessing real companies.

Live effects are opt-in per invocation: `--allow-network` authorizes website collection and `--allow-codex` authorizes subscription-backed assessors. See [runtime capabilities](docs/runtime-capabilities.md) before using either.

Development tools (Ruff, build) are an optional extra: `pip install -e '.[dev]'`, then `ruff check src tests && ruff format --check src tests`.

## Read the specifications

1. [Product and acceptance](docs/specs/01-product.md)
2. [Evidence collection](docs/specs/02-collection.md)
3. [Labeling and adjudication](docs/specs/03-labeling.md)
4. [Telemetry and cost estimation](docs/specs/04-measurement.md)
5. [Experiment and evaluation](docs/specs/05-evaluation.md)
6. [Architecture and implementation plan](docs/specs/06-delivery.md)
7. [Local storage, caching, and idempotency](docs/specs/07-storage.md)
8. [Asynchronous scheduling and scale](docs/specs/08-scheduling.md)

[Domain glossary](CONTEXT.md) defines the canonical terms. Product requirements and proposed implementation defaults are distinguished in the specs.

## Independence and data boundaries

Pramana is provider-agnostic. Consumers supply company identities through a common input contract; provider-specific integrations remain outside the core.

Tracked repository content contains reusable software, specifications, and synthetic fixtures only. Consumer records, credentials, captured website content, evidence bundles, agent inputs and outputs, and experiment artifacts must remain in consumer-controlled, Git-ignored runtime storage (default: `.local/` inside the checkout). They must not appear in documentation, fixtures, logs committed to Git, issues, or pull requests. Examples must be synthetic; anonymizing a consumer record does not make it an approved fixture.

## License

[MIT](LICENSE). The license covers this software only; it grants no rights over third-party data or websites that the tool collects from.

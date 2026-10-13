# Repository Guidelines

## Project Structure & Module Organization

Pramana verifies company–website relationships through deterministic evidence collection, three independent labelers, and adjudication. The repository contains a working local pilot implementation (version 0.2.0) alongside the specifications. No dataset is distributed.

- `README.md`: project status and specification index.
- `CONTEXT.md`: canonical domain vocabulary.
- `docs/specs/01-product.md` through `08-scheduling.md`: product contracts, collection, labeling, measurement, evaluation, delivery, storage, and scheduling.
- `src/pramana/`: the implementation; `tests/test_*.py`: the offline suite.
- `docs/implementation.md`: implemented subset, deviations, and recorded verification.
- `docs/v0-findings.md`, `docs/checkpoint-2026-09-22.md`: pilot results and next steps.
- `.local/`: Git-ignored, consumer-controlled runtime storage.

The specifications remain the contract; `docs/implementation.md` records where the code falls short of them.

## Build, Test, and Development Commands

Python 3.12+, standard library at runtime, setuptools packaging. CI (`.github/workflows/tests.yml`) runs the offline suite and Ruff against a SQLite built from source.

`Store` refuses to open its database unless the linked SQLite is >= 3.51.3 (or the patched 3.50.7 / 3.44.6 backports). Many system libraries are older, so store-touching commands need a patched build on the loader path (see README "Requirements"), e.g. `LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib`:

- `LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m unittest discover -s tests -v`: the offline suite.
- `LD_LIBRARY_PATH=$HOME/.local/pramana-sqlite/lib PYTHONPATH=src python3 -m pramana smoke --run smoke-100 --cases 100`: end-to-end synthetic run.
- `ruff check src tests` and `ruff format --check src tests`: lint and formatting.

For documentation changes:

- `git diff --check`: check whitespace errors in tracked changes.
- `git diff --stat`: review the scope of tracked edits.
- `git status --short`: identify modified and newly created files before staging.

Manually verify relative Markdown links and consistency across affected specifications.

## Coding Style & Naming Conventions

Follow the existing Markdown style: descriptive headings, short paragraphs, hyphen bullets, and relative links. Name new specification files consistently with `NN-topic.md`. Use terminology from `CONTEXT.md`, especially “case,” “evidence bundle,” and “reference label.” Distinguish requirements from proposed defaults.

Python uses four-space indentation and Ruff at 100 columns, with the `E4`, `E7`, `E9`, `F`, `I` and `UP` rule sets. Ruff and `build` are development extras, never runtime dependencies.

## Testing Guidelines

Standard-library `unittest`; no coverage threshold is configured. Follow the verification surfaces in `docs/specs/06-delivery.md`: synthetic fixtures, deterministic extraction, scheduling/recovery, contract validation, and cost reconciliation. Keep offline tests separate from network and model-assisted runs. The whole suite must run without network or model calls.

Behavior changes are versioned rather than edited in place: `contracts.SCHEMA` (`pramana.v1`) is the frozen canonical hash envelope, and new behavior goes into `CURRENT_SCHEMA`, a new `collection.version`, a new prompt module, or a new `rubric_version`. A changed configuration requires a new run ID.

## Commit & Pull Request Guidelines

Existing commits use concise `docs: <imperative description>` subjects. Keep changes focused. In pull requests, summarize the changed contract, link relevant specifications or issues, report validation performed, and identify unresolved decisions. Describe proposed behavior accurately as unimplemented where applicable.

## Data Boundaries

Commit only reusable specifications, software, and synthetic fixtures. Keep consumer records, credentials, website captures, and agent artifacts in Git-ignored runtime storage. Anonymized consumer records are not approved fixtures. Review aggregate findings for disclosure risk before publication.

# Lateralus Pramana

Evidence-based verification of company–website relationships.

Pramana collects website evidence deterministically, obtains three independent agent labels, and asks a judge to adjudicate every case. The resulting reference dataset supports development of a deterministic production verifier. Agent review is bounded to experiments; it is not required for every production record.

## Status

Specification draft, 2026-09-19. No collector, agent integration, production verifier, or dataset has been implemented. No external data has been imported and no paid API has been configured.

## Read the specifications

1. [Product and acceptance](docs/specs/01-product.md)
2. [Evidence collection](docs/specs/02-collection.md)
3. [Labeling and adjudication](docs/specs/03-labeling.md)
4. [Telemetry and cost estimation](docs/specs/04-measurement.md)
5. [Experiment and evaluation](docs/specs/05-evaluation.md)
6. [Architecture and implementation plan](docs/specs/06-delivery.md)

[Domain glossary](CONTEXT.md) defines the canonical terms. User-approved direction and proposed implementation defaults are distinguished in the specs.

## Independence and data boundaries

This is a standalone Lateralus project. Company inputs are provider-neutral; ZoomInfo and AlphaSearch are potential external sources, not runtime dependencies. Do not import application code, credentials, or source datasets into this repository. Synthetic fixtures may be committed; experiment data and captured websites belong in an external artifact directory.

No open-source license is granted by this scaffold. Ownership and distribution terms are for the owner to establish; repository location alone does not establish rights over third-party data or previously authored code.

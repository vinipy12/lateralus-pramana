# Lateralus Pramana

Evidence-based verification of company–website relationships.

Pramana collects website evidence deterministically, obtains three independent agent labels, and asks a judge to adjudicate every case. The resulting reference dataset supports development of a deterministic production verifier. The full pipeline targets 4M+ rows through asynchronous collection, three concurrent labeler streams, and per-row adjudication. A deterministic-only verifier is a separate production option.

## Status

Specification draft, 2026-09-19. No collector, agent integration, production verifier, or dataset has been implemented. No external data has been imported and no paid API has been configured.

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

No open-source license is granted by this scaffold. Ownership and distribution terms are for the owner to establish; repository location alone does not establish rights over third-party data or previously authored code.

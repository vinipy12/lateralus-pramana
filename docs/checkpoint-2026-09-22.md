# Project checkpoint — 2026-09-22

Pramana is an executable local pilot, not a specification-only scaffold. This checkpoint records implementation progress and the next engineering decisions. Consumer-specific experiments, records and findings remain in Git-ignored runtime storage. Detailed operator handoffs live under the relevant consumer's `handoffs/` directory; they must not be copied into public documentation.

## Accomplished

- Implemented Python packaging, versioned input contracts, deterministic bounded collection/extraction, private content-addressed artifacts, SQLite-backed scheduling, receipts, validation and reports.
- Implemented a subscription-backed Codex adapter with fresh labeler/judge sessions and explicit live-execution authorization. No API-key fallback was introduced.
- Separated operational collection/assessment status from semantic verdicts. Empty evidence is not assessed and consumes no model calls. Verified company domains are derived from selected collected pages only for supported match assessments.
- Added host-owned passage citations and three-state provenance: independent, website-derived and unknown. Historical formats and prompts retain their original interpretation.
- Added the stricter match contract: operating identity plus a supplied second identifier, with cited agreement and provenance. A name alone is insufficient. Citation validity does not establish semantic agreement.
- Fixed complete-response socket handling, cancelled-run reporting, robots redirect/pacing behavior and the crawl-delay/chain-budget collision.
- Introduced collector-v4: active network work shares one chain budget across robots, redirects and retries; required waits consume the total target deadline. Added clearer collection diagnostics while retaining TLS, destination and robots controls.
- Completed additional private development experiments and an AI-assisted evidence audit. Experiment history, sampling corrections, invalid attempts and cumulative execution accounting were retained rather than overwritten.

Current implementation revisions are package 0.2.0, input/configuration pramana.v2, collector-v4, rubric-v2, conservative-v1, codex-evidence-v3 and report v3. These revision names do not expand product scope. Replacement-domain discovery remains deferred to product V2.

## Verification and delivery status

The last source-changing verification recorded 70 passing offline tests plus Ruff lint/format checks. Subsequent experiment execution did not change the frozen application/prompt source. Earlier distribution builds and an installed-wheel synthetic smoke passed at the refactor stage; rebuild packaging after the latest source changes before release.

Completed experiments passed artifact-integrity checks and retain separate operational failures and provisional decisions. This does not establish independent semantic accuracy, production acceptance or capacity for millions of cases. No hosted service or production verifier was introduced.

At this checkpoint, substantial implementation files and documentation remain uncommitted. The existing contributor guide still describes the earlier scaffold. Read the current source and [implementation record](implementation.md) before relying on that older status. Git-ignored runtime storage requires its own backup strategy.

## Next decisions and work

1. Clarify relationship semantics: distinguish positive unrelated-operator evidence from missing continuity evidence; define what explicit former-name, acquisition, parent/subsidiary and trading-brand evidence permits.
2. Define consistent treatment of conflicting identifiers. Decide whether one agreeing attribute can outweigh another conflicting attribute, how provenance/age affect that decision, and what address granularity qualifies as agreement.
3. After those decisions, introduce new prompt/rubric/policy revisions as needed; preserve the existing versions and outputs.
4. Add narrow synthetic regressions for phone-digit conflicts, formatted-equivalent phones, city-only versus street-address evidence, explicit continuity, mixed identifier agreement, and placeholder semantics. Consider deterministic identifier checks without claiming to implement a complete identity verifier.
5. Improve structural output reliability without weakening grounding checks or hiding failed attempts. Any repair/retry policy must be bounded and separately accounted for.
6. Validate sample diversity and connected-group separation before dispatch. Intended negatives are not truth labels; failures remain in denominators.
7. Replay a small frozen development set before another larger experiment. Distinguish prompt-only changes from recollection. Independent human labels are required for independent accuracy claims.
8. Review delivery hygiene, update stale contributor guidance in scope, rebuild distributions, verify privacy boundaries and plan durable runtime backups. Commit/push or production integration are separate actions.

These are proposed next steps, not a newly approved rubric or release threshold. The immediate next step is a concrete semantics decision table backed by the private audit examples.

See [product contract](specs/01-product.md), [labeling contract](specs/03-labeling.md), [evaluation boundaries](specs/05-evaluation.md), [implementation details](implementation.md), and the frozen [V0 retrospective](v0-findings.md). Reachability screening remains upstream; collection coverage, adjudication completion and company-domain accuracy remain distinct measures.

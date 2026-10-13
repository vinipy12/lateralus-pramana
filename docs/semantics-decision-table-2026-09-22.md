# Semantics decision table — design

Date: 2026-09-22. Status: implemented. See the implementation record for the two
places implementation resolved an ambiguity in this design: the host-derived
`identity_domain` and assessor-reported identifier agreement.

This document specifies how a case verdict is derived from assessor-reported
facts. It addresses the first three items of the
[2026-09-22 checkpoint](checkpoint-2026-09-22.md): relationship semantics,
conflicting identifiers, and the placeholder/parked boundary. It proposes
implementation revisions; it does not expand product scope, introduce a
deterministic production verifier, or establish an acceptance threshold.

## Motivation

The most recent strict 100-case pilot adjudicated 76 cases: 16 match, 28
mismatch, 32 uncertain, with 22 not assessed for lack of usable evidence and 2
failed. Verified-domain coverage was 16 percent. An AI-assisted audit reviewed
all 76 adjudications and marked 59 supported, 11 supported with caveat, 3
needing owner review, and 3 needing policy review.

Every one of the 32 uncertain cases carried citations, so they are not
evidence-starved; that population is the separate 22. They are cases where
evidence was found, cited, and still produced no decision.

The six flagged cases fall into three patterns.

**Absence read as disproof.** Three cases returned `mismatch` where the evidence
established a different operating entity but established nothing about whether
the two entities are related. The audit described these as one recurring
overconfident-mismatch pattern. A missing continuity check is not evidence of
unrelatedness.

**Continuity evidence not credited.** One case carried an explicit former-name
statement on the website plus agreement on both a supplied phone and a supplied
address, and still adjudicated uncertain under the conservative continuity
policy.

Current behavior is therefore wrong in both directions: too strong on mismatch,
too weak on match.

**No hierarchy for mixed agreement and conflict.** One case had an exact name
and a complete street address in agreement with a conflicting phone, and
adjudicated uncertain, while other cases in the same run accepted a matching
phone despite a changed address. The frozen policy has no rule for mixed
outcomes, so the result depends on the assessor rather than the policy.

**Placeholder never reached `parked`.** One case was a template shell with
placeholder body text, an `example.com` contact address and a dummy phone, and
returned uncertain. The rubric already places corroborated placeholder evidence
in `parked`. Across all 76 adjudications `parked` was never returned, so that
verdict path is effectively unused.

## Governing principle

**A decisive verdict requires positive evidence. Absence of evidence yields
`uncertain`, never `mismatch`.**

This is a requirement, not a default. The three overconfident mismatches above
are each a violation of it.

## The decision table

Stages are evaluated in order. The first stage that yields a verdict stops
evaluation.

### Stage 0 — site substance

| Assessor reports | Verdict |
| --- | --- |
| `parked` — corroborated sale or parking evidence | `parked` |
| `placeholder` — template or dummy content, no operating presence | `parked` |
| `substantive` | continue |
| `indeterminate` | continue |

### Stage 1 and 2 — operator identity and relationship

| Operator identity | Relationship direction | Verdict |
| --- | --- | --- |
| `matches_supplied` | any | continue to Stage 3 |
| `different_operator` | `evidenced_continuity` | continue to Stage 3 |
| `different_operator` | `evidenced_unrelated` | `mismatch` |
| `different_operator` | `no_evidence` | `uncertain` |
| `indeterminate` | any | `uncertain` |

`no_evidence` is a required, first-class value rather than an absent field, so
that "no continuity evidence was found" cannot be represented the same way as
"unrelatedness was established."

### Stage 3 — supplied identifiers

| Agreeing identifiers | Conflicting identifiers | Verdict |
| --- | --- | --- |
| at least 1 | any | `match` |
| 0 | at least 1 | `uncertain` |
| 0 | 0 | `uncertain` |

Conflicting identifiers are recorded on the result even when the verdict is
`match`.

Agreement outranks conflict because agreement on an exact phone number or street
address is unlikely to occur by chance, while a conflicting one is routine after
a relocation or a number change. The final row preserves the existing strict
rule that an operating-name match alone is insufficient.

### Address granularity

A supplied location agrees only at street level, meaning street and number.
Agreement at city or region level alone is recorded as
`insufficient_granularity` and treated as absent rather than as agreement or
conflict.

### Rules to revisit

Two rules are deliberate choices rather than consequences of the governing
principle. Both should be re-examined against the next run's audit.

1. **Agreement outranks conflict unconditionally.** A site matching one stale
   identifier while conflicting on others still yields `match`. A stricter
   variant would require agreeing identifiers to outnumber conflicting ones.
2. **`evidenced_unrelated` yields `mismatch`.** This still lets an assessor's
   judgment of unrelatedness drive a decisive verdict. A stricter variant would
   route every `different_operator` case to `uncertain`.

## Assessment output schema

A new prompt revision, `codex-evidence-v4`, replaces the singular
`corroboration` object with structured findings and adds the two fields the
stages require.

| Field | Type | Notes |
| --- | --- | --- |
| `site_substance` | `substantive \| placeholder \| parked \| indeterminate` plus a passage | Stage 0 |
| `operator_identity` | `matches_supplied \| different_operator \| indeterminate` plus a passage | Stage 1 |
| `relationship.direction` | `evidenced_continuity \| evidenced_unrelated \| no_evidence` | Required whenever `operator_identity` is `different_operator` |
| `identifier_findings[]` | `{field, value_index, outcome, passage_id}` | `outcome` is `agree \| conflict \| insufficient_granularity \| absent` |

`field` and `value_index` keep their present meaning: a reference into the
supplied company fields. The existing `relationship.type` enum is unchanged.

The assessor continues to emit `verdict`, but it becomes a cross-check rather
than the authority. Divergence between the assessor's verdict and the derived
verdict is recorded as a diagnostic, in the same manner as judge overrides.

The three labelers emit facts, the judge adjudicates them as it does today, and
the derivation runs over the judge's fact set.

## Derivation module

A new module, `decision.py`, at version `decision-v1`, exposes a pure function
from a fact set to `(verdict, reason_codes, rule_trace)`. It performs no
input/output, makes no model or network calls, and depends on no storage. The
rule trace records which table row produced the verdict so that every derived
verdict remains auditable.

It is applied in `results.py`, where versioned case results are already derived
from immutable assessments.

## Validation

`validation.py` gains structural checks only. Semantic agreement remains the
assessors' responsibility.

- An `agree` or `conflict` outcome requires a resolvable passage.
- `different_operator` requires a relationship direction.
- `value_index` must reference a field actually supplied for that case.
- `site_substance` values other than `substantive` require a passage.

## Testing

Offline synthetic regressions, with no network or model calls, covering the
surfaces named in checkpoint item 4:

- phone conflicts differing only in digits;
- formatted-equivalent phones that must count as agreement;
- city-only versus street-level address agreement;
- explicit former-name continuity with agreeing identifiers;
- mixed agreement and conflict across identifiers;
- placeholder, parked and substantive substance;
- `different_operator` with `no_evidence`, which must yield `uncertain` — the
  regression covering the three flagged overconfident mismatches.

Each table row above requires at least one test. The derivation module is a pure
function, so every row is testable without a model call.

## Versioning and compatibility

| Field | Value |
| --- | --- |
| `prompt_version` | `codex-evidence-v4` |
| `rubric_version` | `rubric-v3` |
| `relationship_policy_version` | a new evidence-directional revision, replacing `conservative-v1` |
| `result_version` | a new revision |
| `decision_version` | `decision-v1` |

`contracts.SCHEMA` remains frozen at `pramana.v1`; no existing blob identity or
manifest changes. `default_config()` and `validate_config()` change together
under the exact-key rule. A changed configuration requires a new run ID.

Existing prompts, rubrics and results remain available and retain their original
interpretation.

## Limitations

**Prior runs cannot be re-scored.** Assessments produced before
`codex-evidence-v4` do not carry the structured facts the table consumes. The
frozen pilot results stand as they are, and the next run's verdict distribution
is not directly comparable to theirs.

**The accuracy baseline is unmeasured.** Independent semantic accuracy has not
been established for any prior run. This design makes the rubric more decisive,
which converts uncertain cases into decisive verdicts at an error rate that no
measurement has yet bounded. A coverage improvement in the next run is therefore
not evidence of a quality improvement. Establishing that baseline through
independent labels remains a separate, still-required piece of work.

**The audit was AI-assisted.** The 59 supported and 11 caveated adjudications
behind this design were not independently human-verified, so the patterns above
are a reading of the evidence rather than confirmed defects.

## Next step

An implementation plan, followed by the schema and module changes with their
regressions, then a small development run on authorized development cases before
any larger experiment.

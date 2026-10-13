# Conflicting identifiers as positive evidence — design

Date: 2026-09-22. Status: implemented as `decision-v2`; the offline re-derivation matched the expected outcome stated below.

This document proposes one change to the [semantics decision
table](semantics-decision-table-2026-09-22.md): Stage 2 credits conflicting
supplied identifiers, so that a decisive `mismatch` is reachable from cited
evidence rather than only from an assessor's declaration of unrelatedness. It
changes no assessor output schema, introduces no deterministic verifier, and
establishes no acceptance threshold.

## Motivation

The decision table was implemented and exercised in two authorized live runs. The
development replay applied it to the same ten development records as the earlier
strict run: 7 assessed, 3 not assessed, 0 failed, 0 rejected outputs, 28 sessions.
Derived verdicts were 4 `match` and 3 `uncertain`; assessor verdicts were 5
`match` and 2 `mismatch`.

Both `different_operator` cases derived `uncertain` through
`stage2:different_operator/no_evidence`. In each, the assessor established a
different operating entity on substantive content and reported **both a supplied
phone and a supplied address as `conflict`**, each against a cited passage. One of
the two was an intended negative that the earlier strict run had called
`mismatch`.

No assessor in either live run reported `evidenced_unrelated`. That is not a
prompt defect to be tuned away: a website states what it is, not what it is not,
so cited evidence that two entities are unrelated is close to unobtainable. The
consequence is that the only path to `mismatch` in the current table is one that
real evidence does not supply. `mismatch` exists in the rubric and is unreachable
in practice.

The deeper error is a misclassification in the table itself. Two cited passages
contradicting two supplied identifiers is *positive* evidence about the operator's
identity. Treating it as "no evidence" conflates it with the case the governing
principle was written to protect — a different operator where no continuity check
was performed at all.

## Governing principle, unchanged

**A decisive verdict requires positive evidence. Absence of evidence yields
`uncertain`, never `mismatch`.**

This change does not weaken that principle; it corrects which findings count as
evidence. `no_evidence` continues to mean that no continuity evidence was found,
and on its own it continues to yield `uncertain`. What becomes decisive is the
conjunction of a cited different operator with two cited identifier
contradictions and no agreement.

## The revised Stage 2

Stages 0, 1 and 3 are unchanged. Stage 2 gains one row, evaluated before the
existing `no_evidence` row.

| Operator identity | Direction | Identifier findings | Verdict |
| --- | --- | --- | --- |
| `matches_supplied` | any | — | continue to Stage 3 |
| `different_operator` | `evidenced_continuity` | — | continue to Stage 3 |
| `different_operator` | `evidenced_unrelated` | — | `mismatch` |
| `different_operator` | `no_evidence` | 0 agreeing; counted conflicts on at least 2 distinct fields | `mismatch` |
| `different_operator` | `no_evidence` | anything else | `uncertain` |
| `indeterminate` | any | — | `uncertain` |

The new row's reason code is `conflicting_identity`, and its rule trace is
`stage2:different_operator/conflicting_identifiers`, which is what distinguishes
it from the `evidenced_unrelated` row in an audit. No reason code is added: the
derived vocabulary stays inside the frozen `validation.REASONS` set, so the
`codex-evidence-v4` output schema the model receives is untouched.

A conflict is *counted* when its finding has outcome `conflict` and the supplied
field's dependence is not `website_derived`. Two counted conflicts on `phones[0]`
and `phones[1]` are one changed number, not two contradictions, so the threshold
is met only by counted conflicts on two distinct fields — in practice a phone
and an address, or either with a social profile. The same cited passage may
support both. A `website_derived` conflict stays recorded on the result but does
not count: a value taken from the website that the website no longer shows says
the site's contact details changed, which is weak evidence about identity in
either direction, and excluding it keeps conflict symmetric with the provenance
rule already applied to agreement.

Three properties of the new row are deliberate.

**Two fields, not one conflict.** A single conflicting identifier is the routine
consequence of a relocation or a changed number. Contradiction on two distinct
fields is what separates "this record is stale" from "this is a different
organization". One conflict, or two on the same field, continues to yield
`uncertain`.

**Zero agreements required.** If any supplied identifier agrees, Stage 3 already
reaches `match`, and this row must not compete with it. A site that agrees on a
phone and conflicts on an address is not a mismatch.

**`evidenced_continuity` still short-circuits.** An explicit former-name or
acquisition statement routes to Stage 3 before this row is considered, so an
acquired company whose site carries new contact details but states its former
name is unaffected.

`evidenced_unrelated` is retained as a decisive path even though no live run has
produced it. Removing it would discard a genuinely decisive case if evidence ever
supplies one, and it costs nothing to keep.

## Rules deliberately left alone

The previous design named two rules for re-examination. Only one is addressed
here.

**Agreement outranks conflict unconditionally** (Stage 3) is unchanged. No case in
either live run mixed agreement and conflict on the same operator, so there is no
evidence to act on. Revisit it when a run produces one.

## What does not change

The assessor output schema, `codex-evidence-v4`, is unchanged, because
`identifier_findings` already carry per-identifier `conflict` outcomes against
supplied values with cited passages. No new prompt revision, no new prompt hash,
no recollection and no new model calls are required to adopt this rule.
`contracts.SCHEMA` remains frozen at `pramana.v1`.

## Versioning

| Field | Value |
| --- | --- |
| `decision_version` | `decision-v2` |
| `result_version` | `pramana.result.v4` |
| `relationship_policy_version` | `evidence-directional-v1`, unchanged |
| `prompt_version` | `codex-evidence-v4`, unchanged |
| `rubric_version` | `rubric-v3`, unchanged |

Only the decision revision moves. The relationship policy is unchanged because
the meaning of every `direction` value is unchanged; what changed is how the
table weighs identifier findings, and that is what `decision_version` names.
`decision-v1` remains selectable and keeps its behavior, so the replay's
committed results retain their original interpretation. `default_config()` and
`validate_config()` change together under the exact-key rule; the pairing that
ties `rubric-v3` and `evidence-directional-v1` to a derived decision now accepts
either decision revision. A changed configuration requires a new run ID.

The result record must name the decision revision that produced it, and
`case_result` must be told which revision to apply rather than defaulting to the
newest, so that exporting an older run can never silently re-score it.

## Experiment: offline re-derivation

Because the rule consumes only facts that `codex-evidence-v4` already recorded,
its effect is measurable with **no model calls and no network access**. Derive
both `decision-v1` and `decision-v2` verdicts over the 7 assessed fact sets
already committed in the development replay and compare them per case.

The expected outcome, stated before running it: the 4 matches and the
city-only-granularity `uncertain` are untouched, and the 2 `different_operator`
cases move from `uncertain` to `mismatch`, restoring the intended negative the
earlier strict run rejected while keeping every other verdict fixed. A result
other than that is a defect in either the rule or this reading of the facts.

This is a 7-case consistency check on one development set, not an accuracy
measurement.

## Limitations

**The pilot's mismatches cannot be re-scored, and the rule's effect on them is
unknown.** All 28 mismatches in the strict pilot recorded free-text conflicting
evidence, and none recorded a relationship. Free text is not a per-identifier
finding against a supplied value, so it cannot be mapped onto this rule. Whether
the three flagged overconfident mismatches would derive `mismatch` again under
`decision-v2` is not recoverable from those artifacts. The argument for the
two-conflict threshold rests on what the threshold requires, not on evidence that
those three cases fall outside it.

**One assessed intended negative motivates this change.** The replay produced two
`different_operator` cases, one of them an intended negative. Intended negatives
are not truth labels. A rule inferred from two cases may not survive a larger
run.

**This makes the rubric more decisive again.** `decision-v1` converted uncertain
cases into decisive verdicts at an unmeasured error rate; `decision-v2` does so
once more, in the direction of rejection. No independent accuracy baseline exists
for any run, so a mismatch count moving toward the intended negatives is not
evidence of correctness.

**Records with one supplied identifier can never reach `mismatch`.** Four of the
ten development records supply a single identifier field, and for them the
two-field threshold is unsatisfiable. That is accepted: less supplied evidence
supports less decisive rejection, and `match` already carries the same
dependence on what was supplied. It should be reported as a coverage property
of the record, not hidden.

**The unrelatedness judgment has not been eliminated, only bounded.** The
assessor still decides `different_operator` and still decides that a passage
contradicts a supplied value. The table now requires two such decisions to agree
before rejecting, which raises the bar without removing the dependence.

## Next step

An implementation plan, then `decision-v2` with one regression per changed and
unchanged table row, then the offline re-derivation over the replay's committed
facts. A live run is not required to evaluate this change and should not be spent
on it.

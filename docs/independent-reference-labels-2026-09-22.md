# Independent reference labels — design

Date: 2026-09-22. Status: implemented. `recorded` is supplied by the importer rather than stamped at import, so that content-based idempotency holds and the timestamp describes the review rather than the import.

This document specifies how independently produced labels enter the system and
how agreement against them is reported. It exists to close the limitation every
preceding design records: no run has an independent accuracy baseline, so each
increase in decisiveness has an unbounded error rate. It does not propose an
acceptance threshold, does not make any label authoritative over an agent
decision, and does not itself establish accuracy for any existing run.

## What is missing

`evaluation.reference_metrics` already computes the confusion matrix, false-match
rate, false-rejection rate, decisive coverage, uncertain rate and failure rate
that [evaluation](specs/05-evaluation.md) specifies. It has no caller outside its
own test, because no reference label can be recorded. `reporting.py` derives
`reference_origin` as `synthetic` or `agent_adjudicated`, and
[labeling](specs/03-labeling.md) promises that human overrides create new records
with reasons, but no storage, ingestion or metric exists for them.

So the gap is not the metric. It is that the system has nowhere to put a label it
did not produce.

## What a reference label is, and is not

A reference label is one reviewer's verdict for one case, recorded with its
reason. It is **not** authoritative: it never replaces a derived verdict, never
changes a published result, and never feeds back into assessment. Its only
purpose is to be disagreed with, so that disagreement can be counted.

Intended negatives stay out. A `synthetic_mismatch` stratum records what a case
was constructed to be, not what the evidence shows, and the specifications are
explicit that intended negatives are not truth labels. Admitting them here would
manufacture a baseline out of the sampling method.

## Evidence scope

A reviewer who consults the live website, a search engine or a registry is
answering a different question from one who reads only the frozen bundle. Both
are worth measuring and they must never be pooled.

| Scope | Judged from | A disagreement means |
| --- | --- | --- |
| `packet` | The frozen bundle alone | The assessor or the decision table was wrong |
| `open_web` | Any source the reviewer chose | Either that, or collection was insufficient |

`evidence_scope` is required on every label and the report computes each scope's
matrix and rates separately. Without it an open-web disagreement would be counted
as an assessment error, attributing a collection limit to the rubric. Labels
recorded before this field existed keep a null scope and are counted as
`unscoped_legacy`, never folded into either baseline.

## Origin and blindness

Two origins, because they support different claims.

| Origin | Meaning | Admitted to the baseline |
| --- | --- | --- |
| `independent_human` | A reviewer's verdict from the evidence | Only when `blind` is true |
| `owner_review` | A reviewer's verdict after seeing the derived verdict | Never |

`blind` is a declaration by the importer that the reviewer did not see the
derived verdict, the assessor verdicts, or the intended-negative flag. Nothing in
the system can verify that declaration, so the record also keeps `recorded`, and
the report states whether each blind label was recorded before or after the run
reached a terminal state. A blind label recorded afterwards is a declaration
resting on process discipline alone, and the report says so rather than implying
otherwise.

Baseline metrics are computed over blind `independent_human` labels only.
`owner_review` labels are recorded, counted and reported separately. They are
useful — they show where an owner disagrees with the rubric — but an assessment
that has already been seen cannot measure the assessor that produced it.

## Records

Reference labels are append-only. A reviewer who changes their mind adds a record;
nothing is overwritten, matching how every other assessment in the system is
retained.

`ReferenceLabel` fields: `case_id`, `verdict` (the four rubric verdicts),
`reviewer` (an opaque identifier, never a personal name), `origin`, `blind`,
`rationale`, and `recorded`, all required. `recorded` is when the reviewer
produced the label, supplied by the importer: a time stamped at import would
describe the import and would make the after-the-run check meaningless. The record is stored as a content-addressed artifact
and referenced by a row keyed `(run, case_id, reviewer, sequence)`, so artifact
integrity is checked by `store.verify` alongside every other reference. An update
trigger makes rows immutable, as for `labels`, `events`, `receipts` and
`attempts`.

Importing is idempotent by content: re-importing a byte-identical record for the
same case and reviewer is a no-op rather than a second record, so a re-run of an
import does not inflate counts. A record that differs in any field is a new
sequence. Each accepted record writes an event, so the run's event snapshot
advances and a report exported afterwards lands in a new file rather than
conflicting with one already published.

Validation rejects an unknown verdict, an unknown origin, a non-boolean `blind`,
an empty reviewer or rationale, and any case that is not in the run. It does not
require the case to have been assessed: a reviewer may label a case the pipeline
could not assess, and that is worth recording precisely because it shows what
coverage is losing.

## Reporting

When a run has at least one reference label, the report gains a
`reference_agreement` block built from `evaluation.reference_metrics`, plus
per-origin and per-blindness counts, the count of blind labels recorded after the
run ended, and the count of reference labels for cases with no derived verdict.
Those last cases are excluded from the matrix and reported separately, keeping
operational failure out of semantic denominators as `05-evaluation` requires.

`reference_origin` becomes `independent_human` when the baseline is non-empty,
and otherwise keeps its present value. `report_version` becomes `v6` only for a
report carrying the block, so existing exports remain byte-identical and
re-exportable.

The report must not present agreement as accuracy without its denominators. Every
rate is emitted as numerator, denominator and value, which `reference_metrics`
already does, and the report's limitations continue to state that a reference set
this small measures agreement with a reviewer rather than real-world correctness.

## Deliberately out of scope

**Cross-revision accuracy comparison.** Whether `decision-v2` is more accurate
than `decision-v1`, rather than merely more decisive, is answerable offline over
committed fact sets once blind labels exist. That is an analysis, not a report
feature, and building it into `reporting.py` would duplicate derivation there.

**A review interface.** Ingestion is a JSONL import, and `review.py` writes the
packets a reviewer reads, but no interactive tool exists and none is planned
before labels have been produced at least once by hand.

**Adjudicating between reviewers.** Multiple reviewers per case are recorded and
counted, but no consensus rule is defined. Defining one before observing how
reviewers disagree would be inventing policy.

## Versioning

| Field | Value |
| --- | --- |
| `report_version` | `v6`, only when a reference block is present |
| Storage | One additive table; existing databases gain it on open |
| `result_version` | unchanged; results carry no reference label |

No assessor prompt, rubric, relationship policy or decision revision changes. No
existing artifact identity changes.

## Limitations

**This builds the instrument, not the measurement.** After this change the system
can record and report a baseline; it still has none. No accuracy claim becomes
available until blind labels are actually produced for a run.

**A declared blindness is not an enforced one.** The strongest guarantee here is
that non-blind and after-the-fact labels are visibly separated, not that blind
labels are truly blind.

**A cross-case view can leak what a packet withholds.** A packet shows one case
at a time in a seeded order, but a list of many cases side by side can reveal how
the sample was constructed — for example that two cases share one website, which
identifies a constructed pairing. Blindness therefore constrains how case sets are
summarised, not only what a packet contains.

**One reviewer is not ground truth.** A reference label is a human judgment from
the same evidence, which can be wrong, and the vocabulary in `CONTEXT.md` avoids
"ground truth" for exactly this reason. Disagreement localizes a dispute; it does
not settle it.

## Blindness by construction

A declared `blind` is weak. Ordering makes it structural: freeze evidence with
`collect`, write packets, label them, and only then run the assessors. A verdict
that did not exist when the label was recorded cannot have been seen, and the
report's count of blind labels recorded after the run ended corroborates the
declaration instead of trusting it.

`review.py` writes one packet per case with usable evidence, containing the
supplied company fields, the frozen passage catalog the assessors will read, and
the verdict definitions. It withholds the verdict, reason codes, assessor and
judge output, derived results, the sampling stratum, the synthetic flag, the
partition and the source record reference, and lists what it withheld so a
reviewer knows what they are not being shown. Packet order is shuffled by the
run's recorded seed, so position cannot hint at how cases were sampled. A
`labels-template.jsonl` accompanies the packets with the fields a reviewer fills
in; the template deliberately fails validation until the placeholders are
replaced.

The development replay's seven assessed cases cannot be labelled blind by anyone
who has read their derived verdicts. They remain reviewable by someone who has
not.

## Next step

Produce blind labels for a set with no prior verdict, then compare `decision-v1`
against `decision-v2` on correctness rather than decisiveness.

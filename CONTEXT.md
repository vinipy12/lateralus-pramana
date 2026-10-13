# Pramana

Pramana evaluates whether a website represents an expected company using traceable evidence.

## Language

**Company identity**: The expected organization and its independently sourced identifying attributes, including their provenance and age.
_Avoid_: Ground truth company

**Case**: A proposed association between one company identity and one candidate domain. Multiple cases may share a domain. The caller supplies reachable candidates; reachability screening is outside Pramana.
_Avoid_: Domain record

**Website evidence**: Observations collected from a website at a particular time, including failures and redirects. Availability alone is not evidence of company identity.

**Evidence bundle**: An immutable version of the website evidence available for a case assessment.

**Reference label**: A verdict with evidence and recorded origin. Agent-adjudicated reference labels are provisional rather than human-verified truth.
_Avoid_: Gold label, ground truth

**Labeler**: One of three independent assessors of the same case and evidence bundle.

**Judge**: An assessor that adjudicates every evidence-bearing case using its evidence and the three independent labels, including unanimous cases.

**Uncertain**: A valid assessment that the available evidence does not justify a decisive verdict. It differs from an agent or collection execution failure.

**Relationship**: An observed connection such as parent, subsidiary, brand, or rebrand that may explain an apparent identity difference.

**Deterministic verifier**: Versioned rules that map a company identity and a frozen evidence bundle to a verdict without model inference.

**Holdout**: Cases reserved for evaluation and excluded from rule development.

**Not assessed**: An operational outcome after collection yields no usable passages. No model verdict is created; the case remains in coverage denominators.

**Verified company domain**: The normalized hostname of a collected website explicitly selected by a valid, evidence-supported match assessment. Subdomains are preserved. This is provisional when the assessment is agent-derived.

"""Pure verdict derivation from assessor-reported facts; the applied table row is recorded.

A decisive verdict requires positive evidence. Absence of evidence yields
`uncertain`, never `mismatch`. Stages are evaluated in order and the first stage
that yields a verdict stops evaluation. No input/output, no model or network
calls, no storage. Every revision keeps its behavior; callers name the one to
apply so that an older run is never silently re-scored.
"""

DECISION_VERSIONS = ("decision-v1", "decision-v2")
DECISION_VERSION = DECISION_VERSIONS[-1]
PARKED_SUBSTANCE = ("parked", "placeholder")
CONFLICT_FIELDS = 2


def decide(facts, version=DECISION_VERSION):
    """Return (verdict, reason_codes, rule_trace) for one assessor fact set."""
    if version not in DECISION_VERSIONS:
        raise ValueError(f"Unknown decision revision: {version}")
    substance = (facts.get("site_substance") or {}).get("value")
    if substance in PARKED_SUBSTANCE:
        return "parked", ["parking_supported"], "stage0:" + substance
    findings = facts.get("identifier_findings") or []
    outcomes = [finding.get("outcome") for finding in findings]
    operator = (facts.get("operator_identity") or {}).get("value")
    if operator == "different_operator":
        direction = (facts.get("relationship") or {}).get("direction")
        if direction == "evidenced_unrelated":
            return (
                "mismatch",
                ["conflicting_identity"],
                "stage2:different_operator/evidenced_unrelated",
            )
        if direction != "evidenced_continuity":
            if version != "decision-v1" and "agree" not in outcomes:
                if len(counted_conflicts(findings)) >= CONFLICT_FIELDS:
                    return (
                        "mismatch",
                        ["conflicting_identity"],
                        "stage2:different_operator/conflicting_identifiers",
                    )
            return (
                "uncertain",
                ["relationship_unresolved"],
                "stage2:different_operator/no_evidence",
            )
    elif operator != "matches_supplied":
        return "uncertain", ["insufficient_evidence"], "stage1:indeterminate"
    if "agree" in outcomes:
        return "match", ["identity_supported"], "stage3:agreement"
    if "conflict" in outcomes:
        return (
            "uncertain",
            ["conflicting_identity", "insufficient_evidence"],
            "stage3:conflict_only",
        )
    return "uncertain", ["insufficient_evidence"], "stage3:no_identifier"


def counted_conflicts(findings):
    """Distinct fields whose supplied value is contradicted; website-derived values do not count."""
    return {
        finding.get("field")
        for finding in findings
        if finding.get("outcome") == "conflict" and finding.get("dependence") != "website_derived"
    }

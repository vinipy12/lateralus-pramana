"""Reference-agreement metrics and connected-group partitioning.

No release thresholds, model judge prompts or real reference datasets are defined.
"""

from collections import Counter

from .contracts import VERDICTS, digest


def reference_metrics(pairs, accepted):
    matrix = {reference: dict.fromkeys(VERDICTS, 0) for reference in VERDICTS}
    completed = decisive = false_matches = false_rejections = negatives = positives = 0
    for reference, prediction in pairs:
        if reference not in VERDICTS or prediction not in VERDICTS:
            raise ValueError("Unknown verdict")
        matrix[reference][prediction] += 1
        completed += 1
        decisive += prediction != "uncertain"
        negatives += reference in ("mismatch", "parked")
        positives += reference == "match"
        false_matches += prediction == "match" and reference in ("mismatch", "parked")
        false_rejections += prediction in ("mismatch", "parked") and reference == "match"
    if accepted < completed:
        raise ValueError("Accepted denominator cannot exclude evaluated cases")

    def rate(n, d):
        return {"numerator": n, "denominator": d, "value": n / d if d else None}

    return {
        "kind": "reference_agreement",
        "confusion_matrix": matrix,
        "false_match_rate": rate(false_matches, negatives),
        "false_rejection_rate": rate(false_rejections, positives),
        "decisive_coverage": rate(decisive, completed),
        "end_to_end_coverage": rate(completed, accepted),
        "uncertain_rate": rate(completed - decisive, completed),
        "failure_rate": rate(accepted - completed, accepted),
    }


def grouped_split(cases, seed=42, holdout_fraction=0.3):
    """Pilot-size union-find. Synthetic source IDs/families must be supplied by importer."""
    if not 0 <= holdout_fraction <= 1:
        raise ValueError("Invalid holdout fraction")
    cases = list(cases)
    parents = {}

    def root(x):
        parents.setdefault(x, x)
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    keys = {}
    for case in cases:
        values = ["company:" + case["company"]["company_id"], "domain:" + case["candidate_domain"]]
        values += ["family:" + v for v in case.get("corporate_families", [])]
        values += ["company:" + v for v in case.get("synthetic_source_company_ids", [])]
        keys[case["case_id"]] = values
        for value in values[1:]:
            left, right = root(values[0]), root(value)
            parents[max(left, right)] = min(left, right)
    assignments = {}
    for case_id, values in keys.items():
        score = int(digest({"seed": seed, "group": root(values[0])})[:16], 16) / 2**64
        assignments[case_id] = "holdout" if score < holdout_fraction else "development"
    return {
        "method": "connected-components-v1",
        "seed": seed,
        "assignments": assignments,
        "counts": dict(Counter(assignments.values())),
        "requested_holdout_fraction": holdout_fraction,
    }

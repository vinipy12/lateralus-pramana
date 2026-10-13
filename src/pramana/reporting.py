"""Reproducible reports over a committed event snapshot; private by default."""

import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import datetime

from .artifacts import private_dir
from .contracts import EVIDENCE_SCOPES, ROLES, canonical
from .evaluation import reference_metrics
from .evidence import usable_evidence
from .measurement import COUNTERS
from .results import iter_results


def summary(store, run):
    # A read transaction pins a WAL snapshot even when another process is active.
    store.db.execute("BEGIN")
    try:
        result = _summary(store, run)
        store.db.execute("COMMIT")
        return result
    except BaseException:
        store.db.execute("ROLLBACK")
        raise


def _summary(store, run):
    store.verify(run)
    current = store.run(run)
    cases = dict(
        store.db.execute(
            "SELECT state,count(*) FROM cases WHERE run=? GROUP BY state", (run,)
        ).fetchall()
    )
    accepted = sum(cases.values())
    completed = cases.get("completed", 0)
    jobs = [
        dict(row)
        for row in store.db.execute(
            "SELECT role,state,count(*) AS count FROM jobs WHERE run=? GROUP BY role,state", (run,)
        )
    ]
    usage_status, tokens, verdicts = Counter(), Counter(), Counter()
    agreement, pairs, judge_matches = Counter(), Counter(), Counter()
    pair_denominators = Counter()
    invocations = overrides = unanimous_overrides = disagreement_rows = 0
    services = Counter()
    snapshot = store.db.execute(
        "SELECT coalesce(max(seq),0) FROM events WHERE run=?", (run,)
    ).fetchone()[0]
    for row in store.db.execute(
        "SELECT j.role,coalesce(x.usage,r.usage) AS usage,r.duration_ms FROM receipts r JOIN attempts a ON a.id=r.attempt JOIN jobs j ON j.id=a.job LEFT JOIN reconciliations x ON x.attempt=r.attempt WHERE j.run=?",
        (run,),
    ):
        services[row["role"]] += row["duration_ms"] or 0
        if row["role"] not in (*ROLES, "judge"):
            continue
        invocations += 1
        usage = json.loads(row["usage"])
        usage_status[usage["usage_status"]] += 1
        for key in COUNTERS:
            if usage.get(key) is not None:
                tokens[key] += usage[key]
    for row in store.db.execute(
        "SELECT id,current_round,final,state FROM cases WHERE run=?", (run,)
    ):
        labels = {
            r["role"]: store.artifacts.get_json(r["artifact"])["verdict"]
            for r in store.db.execute(
                "SELECT role,artifact FROM labels WHERE run=? AND case_id=? AND round=?",
                (run, row["id"], row["current_round"]),
            )
        }
        for i, left in enumerate(ROLES):
            for right in ROLES[i + 1 :]:
                if left in labels and right in labels:
                    key = left + ":" + right
                    pairs[key] += labels[left] == labels[right]
                    pair_denominators[key] += 1
        if len(labels) != 3:
            continue
        values = list(labels.values())
        count = len(set(values))
        agreement[{1: "unanimous", 2: "two_one", 3: "three_way"}[count]] += 1
        if row["state"] != "completed":
            continue
        final = store.artifacts.get_json(row["final"])
        verdicts[final["verdict"]] += 1
        overrides += final.get("disposition") == "override"
        unanimous_overrides += count == 1 and final["verdict"] != values[0]
        if count > 1:
            disagreement_rows += 1
            for role in ROLES:
                judge_matches[role] += labels[role] == final["verdict"]
    reference = _reference(store, run, accepted)
    wall = None
    if current["ended"]:
        wall = (
            datetime.fromisoformat(current["ended"]) - datetime.fromisoformat(current["created"])
        ).total_seconds()
    operational = {}
    directional = current["config"]["rubric_version"] == "rubric-v3"
    if current["config"]["schema_version"] == "pramana.v2":
        result_counts, derived_verdicts = Counter(), Counter()
        divergences = 0
        for result in iter_results(store, run):
            result_counts[result["assessment_status"]] += 1
            result_counts["verified_domains"] += result["verified_company_domain"] is not None
            if "verdict_divergence" in result:
                derived_verdicts[result["verdict"]] += 1
                divergences += result["verdict_divergence"]
        evidence_cases = 0
        for row in store.db.execute(
            "SELECT bundle FROM rounds r JOIN cases c ON c.run=r.run AND c.id=r.case_id AND c.current_round=r.round WHERE r.run=?",
            (run,),
        ):
            evidence_cases += usable_evidence(store._verified_bundle(row[0]))
        calls_without_evidence = 0
        rejected = 0
        for row in store.db.execute(
            "SELECT j.bundle,r.outcome FROM receipts r JOIN attempts a ON a.id=r.attempt JOIN jobs j ON j.id=a.job WHERE j.run=? AND j.role IN ('labeler_1','labeler_2','labeler_3','judge')",
            (run,),
        ):
            calls_without_evidence += not usable_evidence(store._verified_bundle(row["bundle"]))
            rejected += row["outcome"] == "invalid_output"
        operational = {
            "assessment_status_counts": dict(result_counts),
            "not_assessed_cases": cases.get("not_assessed", 0),
            "failed_cases": cases.get("incomplete", 0),
            "cases_with_usable_evidence": evidence_cases,
            "evidence_coverage": evidence_cases / accepted if accepted else None,
            "verified_domain_cases": result_counts["verified_domains"],
            "verified_domain_coverage": result_counts["verified_domains"] / accepted
            if accepted
            else None,
            "calls_without_usable_evidence": calls_without_evidence,
            "rejected_assessment_outputs": rejected,
        }
        if derived_verdicts:
            operational["derived_verdicts"] = dict(derived_verdicts)
            operational["verdict_divergences"] = divergences
        operational["assessment_status_counts"].pop("verified_domains", None)
    return {
        "report_version": ("v6" if reference else "v4" if directional else "v3")
        if operational
        else "v2",
        **operational,
        "runtime": current["config"]["runtime"],
        "experiment_id": run,
        "event_snapshot": snapshot,
        "configuration_hash": current["config_hash"],
        "state": current["state"],
        "accepted_cases": accepted,
        "completed_cases": completed,
        "incomplete_cases": accepted - completed,
        "case_states": cases,
        "jobs": jobs,
        "end_to_end_coverage": completed / accepted if accepted else None,
        "verdicts": dict(verdicts),
        **({"reference_agreement": reference} if reference else {}),
        "reference_origin": "independent_human"
        if reference and reference["baseline_labels"]
        else "synthetic"
        if current["config"]["runtime"] == "synthetic-v1"
        else "agent_adjudicated",
        "provisional": True,
        "agreement": dict(agreement),
        "agreement_scope": "valid current-round comparisons, including incomplete cases",
        "judge_overrides": overrides,
        "unanimous_overrides": unanimous_overrides,
        "pairwise_agreement": {
            key: {"count": value, "denominator": pair_denominators[key]}
            for key, value in pairs.items()
        },
        "judge_matches_on_disagreement": {
            role: {"count": judge_matches[role], "denominator": disagreement_rows} for role in ROLES
        },
        "invocation_attempts": invocations,
        "usage_status_counts": dict(usage_status),
        "known_tokens": dict(tokens),
        "complete_model_cost": None,
        "cost_missing_reason": "No configured price table; orchestration usage unavailable",
        "wall_seconds": wall,
        "aggregate_service_ms": dict(services),
        "limitations": [
            "Synthetic adapters establish workflow behavior, not assessment quality."
            if current["config"]["runtime"] == "synthetic-v1"
            else "Agent-adjudicated reference labels remain provisional; model access does not establish accuracy.",
            "Reference agreement is not real-world accuracy.",
            "No multi-million-case capacity proof has been completed.",
        ],
    }


def _reference(store, run, accepted):
    """Agreement against independently produced labels, never pooled across evidence scopes."""
    labels = store.reference_labels(run)
    if not labels:
        return None
    ended = store.run(run)["ended"]
    verdicts = {
        result["case_id"]: result["verdict"]
        for result in iter_results(store, run)
        if result["verdict"] is not None
    }
    counts, after = Counter(), 0
    baselines = {scope: {} for scope in EVIDENCE_SCOPES}
    without_prediction = set()
    for label in labels:
        counts["origin:" + label["origin"]] += 1
        counts["blind" if label["blind"] else "sighted"] += 1
        counts["scope:" + (label["evidence_scope"] or "unscoped_legacy")] += 1
        if label["blind"] and ended and label["recorded"] > ended:
            after += 1
        if label["origin"] == "independent_human" and label["blind"]:
            if label["evidence_scope"] in baselines:
                baselines[label["evidence_scope"]][(label["case_id"], label["reviewer"])] = label[
                    "verdict"
                ]
    scoped = {}
    for scope, current in baselines.items():
        pairs = []
        for (case_id, _), verdict in sorted(current.items()):
            if case_id in verdicts:
                pairs.append((verdict, verdicts[case_id]))
            else:
                without_prediction.add(case_id)
        scoped[scope] = {
            **reference_metrics(pairs, max(accepted, len(pairs))),
            "baseline_labels": len(pairs),
        }
    return {
        "kind": "reference_agreement",
        "scopes": scoped,
        "scope_meanings": {
            "packet": "judged from the frozen bundle alone; disagreement is an assessment error",
            "open_web": "judged with outside sources; disagreement may instead be missing collection",
        },
        "label_counts": dict(sorted(counts.items())),
        "baseline_labels": sum(entry["baseline_labels"] for entry in scoped.values()),
        "reviewers": len({label["reviewer"] for label in labels}),
        "blind_labels_recorded_after_run_ended": after,
        "labels_without_derived_verdict": len(without_prediction),
        "baseline_scope": "blind independent_human labels, reported separately per evidence scope",
    }


def markdown(report):
    coverage = report["end_to_end_coverage"]
    return "\n".join(
        [
            "# Pramana experiment",
            "",
            f"State: **{report['state']}**.",
            "",
            f"Accepted: {report['accepted_cases']}; completed: {report['completed_cases']}; incomplete: {report['incomplete_cases']}.",
            f"End-to-end coverage: {coverage:.1%}."
            if coverage is not None
            else "No cases; coverage is undefined.",
            "",
            f"Reference origin: {report['reference_origin']}; provisional: yes.",
            f"Verdicts: {json.dumps(report['verdicts'], sort_keys=True)}",
            "",
            f"Invocation attempts: {report['invocation_attempts']}.",
            f"Usage status: {json.dumps(report['usage_status_counts'], sort_keys=True)}",
            "Complete model cost: **unknown**.",
            "",
            *(
                [
                    f"Not assessed: {report['not_assessed_cases']}; failed: {report['failed_cases']}.",
                    f"Cases with usable evidence: {report['cases_with_usable_evidence']}; verified domains: {report['verified_domain_cases']}.",
                    f"Rejected assessment outputs: {report['rejected_assessment_outputs']}; calls without usable evidence: {report['calls_without_usable_evidence']}.",
                    "",
                ]
                if "not_assessed_cases" in report
                else []
            ),
            *(
                [
                    f"Derived verdicts: {json.dumps(report['derived_verdicts'], sort_keys=True)}",
                    f"Assessor/derived divergences: {report['verdict_divergences']}.",
                    "",
                ]
                if "derived_verdicts" in report
                else []
            ),
            *(
                [
                    f"Reference baseline: {report['reference_agreement']['baseline_labels']} blind labels from {report['reference_agreement']['reviewers']} reviewer(s); counts: {json.dumps(report['reference_agreement']['label_counts'], sort_keys=True)}",
                    *(
                        f"Scope {scope} ({report['reference_agreement']['scope_meanings'][scope]}): "
                        f"{entry['baseline_labels']} labels; false match "
                        f"{json.dumps(entry['false_match_rate'], sort_keys=True)}; false rejection "
                        f"{json.dumps(entry['false_rejection_rate'], sort_keys=True)}"
                        for scope, entry in sorted(report["reference_agreement"]["scopes"].items())
                    ),
                    "Scopes are never pooled: an open_web disagreement may be missing collection rather than an assessment error.",
                    f"Blind labels recorded after the run ended: {report['reference_agreement']['blind_labels_recorded_after_run_ended']}; labels without a derived verdict: {report['reference_agreement']['labels_without_derived_verdict']}.",
                    "Agreement with a reviewer is not real-world accuracy.",
                    "",
                ]
                if "reference_agreement" in report
                else []
            ),
            "## Limitations",
            "",
            *["- " + text for text in report["limitations"]],
            "",
        ]
    )


def _publish(path, chunks):
    """Stream a private atomic snapshot; a repeated export must be byte-identical."""
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".export-")
    try:
        written = hashlib.sha256()
        with os.fdopen(fd, "wb") as stream:
            for chunk in chunks:
                stream.write(chunk)
                written.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            with path.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").digest() != written.digest():
                    raise ValueError("Report snapshot collision")
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def export(store, run):
    # One WAL snapshot covers summary, per-case results, and events, even with another writer.
    store.db.execute("BEGIN")
    try:
        report = _summary(store, run)
        root = private_dir(private_dir(private_dir(store.root / "runs") / run) / "reports")
        suffix = f"{report['report_version']}-{report['event_snapshot']}"
        _publish(root / f"summary-{suffix}.json", [canonical(report)])
        _publish(root / f"report-{suffix}.md", [markdown(report).encode()])
        _publish(
            root / f"cases-{suffix}.jsonl",
            (canonical(row) + b"\n" for row in iter_results(store, run)),
        )
        _publish(
            root / f"events-{suffix}.jsonl",
            (
                (row[0] + "\n").encode()
                for row in store.db.execute(
                    "SELECT payload FROM events WHERE run=? AND seq<=? ORDER BY seq",
                    (run, report["event_snapshot"]),
                )
            ),
        )
        store.db.execute("COMMIT")
        return report, root
    except BaseException:
        store.db.execute("ROLLBACK")
        raise

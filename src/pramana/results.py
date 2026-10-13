"""Provider-neutral case results derived from immutable assessments and evidence."""

from .contracts import ContractError, normalize_url
from .decision import decide


def case_result(case, state, bundle=None, final=None, decision_version=None):
    if state == "completed" and final is None:
        raise ContractError("Completed case is missing its assessment")
    assessed = state == "completed"
    status = (
        "assessed"
        if assessed
        else "not_assessed"
        if state == "not_assessed"
        else "failed"
        if state == "incomplete"
        else "pending"
    )
    pages = bundle["pages"] if bundle else []
    version = final.get("assessment_version", "pramana.v1") if final else None
    directional = assessed and final.get("rubric_version") == "rubric-v3"
    if directional and decision_version is None:
        raise ContractError("A derived result must name its decision revision")
    verdict, reason_codes, rule_trace = (
        decide(final, decision_version)
        if directional
        else (final["verdict"] if assessed else None, None, None)
    )
    if directional:
        domain = final.get("identity_domain") if verdict == "match" else None
        url = final.get("identity_url") if domain else None
    else:
        domain = final.get("verified_company_domain") if verdict == "match" else None
        url = final.get("verified_company_url") if domain else None
    if domain and version != "pramana.v2":
        raise ContractError("Legacy assessment cannot assert a verified domain")
    return {
        "result_version": (
            "pramana.result.v3" if decision_version == "decision-v1" else "pramana.result.v4"
        )
        if directional
        else "pramana.result.v2",
        "case_id": case["case_id"],
        "candidate_url": case["candidate_url"],
        "candidate_domain": case["candidate_domain"],
        "resolved_url": normalize_url(pages[0]["final_url"]) if pages else None,
        "assessment_status": status,
        "operational_state": state,
        "reason": "no_usable_evidence" if status == "not_assessed" else None,
        "verdict": verdict,
        **(
            {
                "assessor_verdict": final["verdict"],
                "verdict_divergence": final["verdict"] != verdict,
                "reason_codes": reason_codes,
                "rule_trace": rule_trace,
                "decision_version": decision_version,
                "site_substance": final.get("site_substance"),
                "operator_identity": final.get("operator_identity"),
            }
            if directional
            else {}
        ),
        "verified_company_domain": domain,
        "verified_company_url": url,
        "domain_status": "verified"
        if domain
        else "legacy_not_recorded"
        if assessed and version == "pramana.v1"
        else "unverified",
        "assessment_version": version,
        "assessment_id": final.get("assessment_id") if assessed else None,
        "company_snapshot_hash": case["company_snapshot_hash"],
        "bundle_id": bundle["bundle_id"] if bundle else None,
        "citations": final["citations"] if assessed else [],
        "relationship": final.get("relationship") if assessed else None,
        **(
            {"corroboration": final.get("corroboration")}
            if assessed and final.get("rubric_version") == "rubric-v2"
            else {"identifier_findings": final.get("identifier_findings")}
            if directional
            else {}
        ),
        "collection_failures": bundle.get("failures", []) if bundle else [],
        "redirects": [
            {
                "url": attempt["url"],
                "status": attempt["status"],
                "location": attempt.get("headers", {}).get("location"),
            }
            for attempt in bundle.get("attempts", [])
            if attempt.get("purpose") == "page"
            and attempt.get("status") in (301, 302, 303, 307, 308)
        ]
        if bundle
        else [],
    }


def iter_results(store, run):
    for row in store.db.execute(
        "SELECT c.*,r.bundle FROM cases c LEFT JOIN rounds r ON r.run=c.run AND r.case_id=c.id AND r.round=c.current_round WHERE c.run=? ORDER BY c.id",
        (run,),
    ):
        case = store.artifacts.get_json(row["snapshot"])
        bundle = store._verified_bundle(row["bundle"]) if row["bundle"] else None
        final = store.artifacts.get_json(row["final"]) if row["final"] else None
        config = store.run(run)
        result = case_result(
            case, row["state"], bundle, final, config["config"].get("decision_version")
        )
        result.update(
            round_id=row["current_round"],
            configuration_hash=config["config_hash"],
            rubric_version=config["config"]["rubric_version"],
            relationship_policy_version=config["config"]["relationship_policy_version"],
        )
        yield result

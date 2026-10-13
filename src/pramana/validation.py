"""Structural, citation and lineage validation, never semantic truth verification."""

from .contracts import ROLES, VERDICTS, ContractError, digest
from .evidence import DIRECTIONS, reconstruct

REASONS = {
    "identity_supported",
    "conflicting_identity",
    "parking_supported",
    "insufficient_evidence",
    "blocked",
    "relationship_unresolved",
    "same_source",
    "unsupported_content",
    "synthetic",
}


def validate_assessment(output, task):
    if not isinstance(output, dict):
        raise ContractError("Assessment must be an object")
    for key in (
        "case_id",
        "round_id",
        "company_snapshot_hash",
        "bundle_id",
        "rubric_version",
        "relationship_policy_version",
        "invocation_id",
        "role",
    ):
        if output.get(key) != task[key]:
            raise ContractError(f"Assessment lineage mismatch: {key}")
    if task.get("assessment_version") == "pramana.v2" or task.get("prompt_version") in (
        "codex-evidence-v2",
        "codex-evidence-v3",
        "codex-evidence-v4",
    ):
        output = reconstruct(output, task)
    if output.get("verdict") not in VERDICTS:
        raise ContractError("Unknown verdict")
    reasons = output.get("reason_codes")
    if not isinstance(reasons, list) or not reasons or any(r not in REASONS for r in reasons):
        raise ContractError("Invalid reason codes")
    if not isinstance(output.get("rationale"), str) or not 0 < len(output["rationale"]) <= 4000:
        raise ContractError("A concise rationale is required")
    if not isinstance(output.get("missing_evidence"), list) or not isinstance(
        output.get("conflicting_evidence"), list
    ):
        raise ContractError("Missing/conflicting evidence lists are required")
    elements = {
        (p["page_id"], e["element_id"]): e for p in task["bundle"]["pages"] for e in p["elements"]
    }

    def citations(values):
        if not isinstance(values, list):
            raise ContractError("Citations must be a list")
        for citation in values:
            if not isinstance(citation, dict) or citation.get("bundle_id") != task["bundle_id"]:
                raise ContractError("Citation bundle mismatch")
            element = elements.get((citation.get("page_id"), citation.get("element_id")))
            if element is None:
                raise ContractError("Unknown citation element")
            excerpt = citation.get("excerpt")
            if not isinstance(excerpt, str) or not excerpt or excerpt not in element["value"]:
                raise ContractError("Citation excerpt does not exist")
            if not isinstance(citation.get("claim"), str) or not citation["claim"].strip():
                raise ContractError("Citation claim is required")

    citations(output.get("citations"))
    if output["verdict"] != "uncertain" and not output["citations"]:
        raise ContractError("A decisive verdict requires citations")
    relationship = output.get("relationship")
    directional = task["rubric_version"] == "rubric-v3"
    unevidenced = False
    if directional:
        if relationship is not None and not isinstance(relationship, dict):
            raise ContractError("Invalid relationship")
        direction = (relationship or {}).get("direction")
        different = output["operator_identity"]["value"] == "different_operator"
        if different != (direction is not None):
            raise ContractError("A different operator requires exactly one relationship direction")
        if direction is not None and direction not in DIRECTIONS:
            raise ContractError("Unknown relationship direction")
        unevidenced = direction == "no_evidence"
        if unevidenced and (relationship.get("type") is not None or relationship["citations"]):
            raise ContractError("Absent continuity evidence cannot assert a relationship")
    if relationship is not None and not unevidenced:
        if not isinstance(relationship, dict) or relationship.get("type") not in (
            "brand",
            "parent",
            "subsidiary",
            "acquisition",
            "rebrand",
            "continuity",
        ):
            raise ContractError("Invalid relationship")
        citations(relationship.get("citations"))
        if not relationship["citations"]:
            raise ContractError("Relationship requires evidence")
    request = output.get("collection_request")
    if request is not None:
        if not isinstance(request, dict) or request.get("missing_fact") not in (
            "operator_identity",
            "relationship_continuity",
            "contact_identity",
        ):
            raise ContractError("Invalid supplemental fact")
        if request.get("category") not in ("about", "contact") or not request.get("rationale"):
            raise ContractError("Invalid supplemental request")
    if task["role"] == "judge":
        if output.get("disposition") not in ("accept", "override", "request_evidence", "uncertain"):
            raise ContractError("Invalid judge disposition")
        if (
            set(output.get("label_ids", [])) != set(task["label_ids"])
            or len(output["label_ids"]) != 3
        ):
            raise ContractError("Judge must reference all three labels")
        if (output["disposition"] == "request_evidence") != (request is not None):
            raise ContractError("Supplemental disposition/request mismatch")
        if (
            output["disposition"] in ("request_evidence", "uncertain")
            and output["verdict"] != "uncertain"
        ):
            raise ContractError("Unresolved adjudications must be uncertain")
    elif task["role"] not in ROLES:
        raise ContractError("Unknown assessor role")
    result = dict(output)
    result["assessment_id"] = digest(output)
    return result

"""Deterministic passage selection and host-owned citation reconstruction."""

from urllib.parse import urlsplit

from .contracts import ContractError, normalize_url

SUBSTANCE = ("substantive", "placeholder", "parked", "indeterminate")
OPERATOR_IDENTITY = ("matches_supplied", "different_operator", "indeterminate")
DIRECTIONS = ("evidenced_continuity", "evidenced_unrelated", "no_evidence")
OUTCOMES = ("agree", "conflict", "insufficient_granularity", "absent")
IDENTIFIER_FIELDS = ("phones", "locations", "social_urls")
NAVIGATION = ("canonical", "html_refresh", "about_link", "contact_link")


def catalog(bundle):
    """Small handles scoped to one immutable bundle, without acquisition metadata."""
    prefix = bundle["bundle_id"][:12]
    pages, passages = {}, {}
    for index, page in enumerate(bundle["pages"], 1):
        handle = f"{prefix}:w{index}"
        pages[handle] = page
        for element in page["elements"]:
            value = element["value"]
            for start in range(0, len(value), 800):
                excerpt = value[start : start + 800]
                if not excerpt.strip():
                    continue
                key = f"{prefix}:p{len(passages) + 1}"
                passages[key] = {
                    "website_page_id": handle,
                    "type": element["type"],
                    "bundle_id": bundle["bundle_id"],
                    "page_id": page["page_id"],
                    "element_id": element["element_id"],
                    "excerpt": excerpt,
                }
    return pages, passages


def reconstruct(output, task):
    """Resolve model selections; never let a model supply the resulting domain or quote."""
    pages, passages = catalog(task["bundle"])

    def citations(values):
        if not isinstance(values, list):
            raise ContractError("Passage selections must be a list")
        result = []
        for selection in values:
            if not isinstance(selection, dict) or set(selection) != {"passage_id", "claim"}:
                raise ContractError("Expected passage ID and claim")
            if not isinstance(selection["passage_id"], str):
                raise ContractError("Passage ID must be a string")
            passage = passages.get(selection["passage_id"])
            if passage is None:
                raise ContractError("Unknown or wrong-bundle passage")
            result.append(
                {
                    **{k: v for k, v in passage.items() if k not in ("website_page_id", "type")},
                    **selection,
                }
            )
        return result

    result = {**output, "assessment_version": "pramana.v2"}
    result["citations"] = citations(output.get("citations"))
    if output.get("relationship") is not None:
        relationship = output["relationship"]
        if not isinstance(relationship, dict):
            raise ContractError("Invalid relationship")
        result["relationship"] = {
            **relationship,
            "citations": citations(relationship.get("citations")),
        }
    if "website_page_id" not in output:
        raise ContractError("Website page selection is required")
    selected = output["website_page_id"]
    directional = task["rubric_version"] == "rubric-v3"
    if directional:
        substance = fact(output, "site_substance", SUBSTANCE, passages)
        operator = fact(output, "operator_identity", OPERATOR_IDENTITY, passages)
        expects_site = substance == "substantive" and operator != "indeterminate"
        domain_key, url_key = "identity_domain", "identity_url"
    else:
        expects_site = output.get("verdict") == "match"
        domain_key, url_key = "verified_company_domain", "verified_company_url"
    result[domain_key] = None
    result[url_key] = None
    if expects_site:
        if not isinstance(selected, str) or selected not in pages:
            raise ContractError("Match requires a collected website page")
        url = normalize_url(pages[selected]["final_url"])
        host = urlsplit(url).hostname
        cited_hosts = {
            urlsplit(
                normalize_url(pages[passages[c["passage_id"]]["website_page_id"]]["final_url"])
            ).hostname
            for c in result["citations"]
        }
        if not any(
            passages[c["passage_id"]]["type"] not in ("canonical", "html_refresh")
            for c in result["citations"]
        ):
            raise ContractError("URL metadata alone cannot verify identity")
        if host not in cited_hosts:
            raise ContractError("Verified domain requires citations on that website")
        result.update({domain_key: host, url_key: url})
    elif selected is not None:
        raise ContractError("Only an identified operating website can be selected")
    if directional:
        result["identifier_findings"] = findings(output, task, result, passages, pages)
    elif task["rubric_version"] == "rubric-v2":
        result["corroboration"] = corroboration(output, task, result, passages, pages)
    if task["role"] == "judge":
        reviews = output.get("label_reviews")
        if not isinstance(reviews, dict) or set(reviews) != {"a", "b", "c"}:
            raise ContractError("Judge must review all three label slots")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 1000 for v in reviews.values()):
            raise ContractError("Each label review must be concise and nonempty")
        result["label_ids"] = task["label_ids"]
    return result


def usable_evidence(bundle):
    return bool(catalog(bundle)[1])


def corroboration(output, task, result, passages, pages):
    """Enforce a supplied second-identifier citation; semantic agreement remains adjudicated."""
    if "corroboration" not in output:
        raise ContractError("Corroboration selection is required")
    selected = output["corroboration"]
    if output.get("verdict") != "match":
        if selected is not None:
            raise ContractError("Only a match can assert corroboration")
        return None
    if not isinstance(selected, dict) or set(selected) != {"field", "value_index", "passage_id"}:
        raise ContractError("Match requires a supplied corroborating identifier")
    field, index, passage = selected["field"], selected["value_index"], selected["passage_id"]
    if not isinstance(field, str) or field not in ("phones", "locations", "social_urls"):
        raise ContractError("Names and domain-derived fields cannot corroborate")
    values = task["company"]["fields"].get(field, [])
    if type(index) is not int or not 0 <= index < len(values) or not values[index].strip():
        raise ContractError("Corroboration must select a supplied identifier")
    dependence = task["company"]["limitations"].get(field, {}).get("dependence", "unknown")
    if dependence == "website_derived" or (field == "social_urls" and dependence != "independent"):
        raise ContractError("Identifier provenance cannot support corroboration")
    if (
        not isinstance(passage, str)
        or passage not in passages
        or passage not in {c["passage_id"] for c in result["citations"]}
    ):
        raise ContractError("Corroborating passage must be cited from this bundle")
    evidence = passages[passage]
    if evidence["type"] in ("canonical", "html_refresh", "about_link", "contact_link"):
        raise ContractError("Navigation metadata cannot corroborate identity")
    host = urlsplit(normalize_url(pages[evidence["website_page_id"]]["final_url"])).hostname
    if host != result["verified_company_domain"]:
        raise ContractError("Corroboration must be on the verified website")
    return {
        **selected,
        "supplied_value": values[index],
        "dependence": dependence,
        "citation": next(c for c in result["citations"] if c["passage_id"] == passage),
    }


def fact(output, key, values, passages):
    """Structured facts carry a passage; the host resolves it, never the assessor's prose."""
    selected = output.get(key)
    if not isinstance(selected, dict) or set(selected) != {"value", "passage_id"}:
        raise ContractError(f"A structured fact is required: {key}")
    if selected["value"] not in values:
        raise ContractError(f"Unknown {key} value")
    passage = selected["passage_id"]
    required = selected["value"] not in ("substantive", "indeterminate")
    if passage is None:
        if required:
            raise ContractError(f"This {key} value requires a cited passage")
    elif not isinstance(passage, str) or passage not in passages:
        raise ContractError(f"Unknown or wrong-bundle passage for {key}")
    return selected["value"]


def findings(output, task, result, passages, pages):
    """Enforce supplied-identifier structure and provenance; agreement remains adjudicated."""
    selected = output.get("identifier_findings")
    if not isinstance(selected, list):
        raise ContractError("Identifier findings are required")
    cited = {citation["passage_id"] for citation in result["citations"]}
    seen, resolved = set(), []
    for item in selected:
        if not isinstance(item, dict) or set(item) != {
            "field",
            "value_index",
            "outcome",
            "passage_id",
        }:
            raise ContractError("Invalid identifier finding")
        field, index = item["field"], item["value_index"]
        outcome, passage = item["outcome"], item["passage_id"]
        if field not in IDENTIFIER_FIELDS:
            raise ContractError("Names and domain-derived fields cannot be identifier findings")
        if outcome not in OUTCOMES:
            raise ContractError("Unknown identifier outcome")
        values = task["company"]["fields"].get(field, [])
        if type(index) is not int or not 0 <= index < len(values) or not values[index].strip():
            raise ContractError("An identifier finding must reference a supplied identifier")
        if (field, index) in seen:
            raise ContractError("One supplied identifier cannot carry two findings")
        seen.add((field, index))
        dependence = task["company"]["limitations"].get(field, {}).get("dependence", "unknown")
        if outcome in ("agree", "conflict"):
            if not isinstance(passage, str) or passage not in passages or passage not in cited:
                raise ContractError("Agreement or conflict must cite a passage from this bundle")
            if passages[passage]["type"] in NAVIGATION:
                raise ContractError("Navigation metadata cannot establish an identifier finding")
        elif passage is not None:
            raise ContractError("Only agreement or conflict may cite a passage")
        if outcome == "agree":
            if dependence == "website_derived" or (
                field == "social_urls" and dependence != "independent"
            ):
                raise ContractError("Identifier provenance cannot support agreement")
            host = urlsplit(
                normalize_url(pages[passages[passage]["website_page_id"]]["final_url"])
            ).hostname
            if result["identity_domain"] and host != result["identity_domain"]:
                raise ContractError("Agreement must be evidenced on the identified website")
        resolved.append(
            {
                **item,
                "supplied_value": values[index],
                "dependence": dependence,
                "citation": next(
                    (c for c in result["citations"] if c["passage_id"] == passage), None
                ),
            }
        )
    return resolved

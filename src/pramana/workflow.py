"""Pure progression policy; the store applies decisions within fenced transactions."""

from urllib.parse import urlsplit

from .evidence import usable_evidence


def admission(bundle, config):
    if config["schema_version"] == "pramana.v2" and not usable_evidence(bundle):
        return "not_assessed"
    return "labeling"


def judge_ready(valid_roles):
    return set(valid_roles) == {"labeler_1", "labeler_2", "labeler_3"}


def supplemental_target(bundle, request, round_id, config):
    if not request or round_id >= config["supplemental_rounds"] or not bundle["pages"]:
        return None
    host = urlsplit(bundle["pages"][0]["final_url"]).hostname
    visited = {
        url for page in bundle["pages"] for url in (page.get("requested_url"), page["final_url"])
    }
    links = sorted(
        {
            link["url"]
            for page in bundle["pages"]
            for link in page["links"]
            if link["category"] == request["category"]
            and urlsplit(link["url"]).hostname == host
            and (config["schema_version"] != "pramana.v2" or link["url"] not in visited)
        }
    )
    proposed = request.get("url")
    return proposed if proposed in links else (links[0] if links and not proposed else None)


def supplemental_changed(previous, collected):
    old = {(e["type"], e["value"]) for p in previous["pages"] for e in p["elements"]}
    return any(
        (e["type"], e["value"]) not in old and e["value"].strip()
        for p in collected["pages"]
        for e in p["elements"]
    )

"""Versioned JSON contracts. Hashes are SHA-256 of canonical UTF-8 JSON.

Canonical v1: sorted object keys, compact separators, Unicode preserved, no NaN,
no implicit Unicode normalization, and array order preserved. Hashes include a
schema envelope; callers include every behavior-affecting configuration in keys.
"""

import hashlib
import ipaddress
import json
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

SCHEMA = "pramana.v1"  # Frozen canonical hash envelope; never change existing blob identities.
CURRENT_SCHEMA = "pramana.v2"
ROLES = ("labeler_1", "labeler_2", "labeler_3")
VERDICTS = ("match", "mismatch", "parked", "uncertain")
FIELDS = ("name", "legal_name", "aliases", "descriptions", "locations", "phones", "social_urls")
REFERENCE_ORIGINS = ("independent_human", "owner_review")
EVIDENCE_SCOPES = ("packet", "open_web")


class ContractError(ValueError):
    """An input or result does not satisfy its declared contract."""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical({"schema": SCHEMA, "value": value})).hexdigest()


def utcnow():
    return datetime.now(UTC).isoformat()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ContractError(
            "Identifiers must be 1–128 ASCII letters, digits, underscores or hyphens"
        )
    return value


def normalize_url(value):
    if not isinstance(value, str) or not value or any(ord(c) <= 32 for c in value):
        raise ContractError("Invalid URL")
    if "\\" in value:
        raise ContractError("Backslashes are not allowed in URLs")
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ContractError("Only HTTP(S) URLs are supported")
    if parsed.username is not None or parsed.password is not None:
        raise ContractError("URL credentials are forbidden")
    try:
        port = parsed.port
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError) as exc:
        raise ContractError("Invalid hostname or port") from exc
    if port not in (None, 80, 443):
        raise ContractError("Port is outside the V1 allowlist")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ContractError("Nonpublic hostname")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", host) or any(not p for p in host.split(".")):
            raise ContractError("Invalid hostname") from None
    else:
        if not public_address(address):
            raise ContractError("Nonpublic destination")
        if address.version == 6:
            host = "[" + host + "]"
    default = 443 if parsed.scheme == "https" else 80
    netloc = host + (f":{port}" if port and port != default else "")
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, ""))


def public_address(address):
    address = ipaddress.ip_address(address)
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_loopback
        and not getattr(address, "ipv4_mapped", None)
    )


def validate_case(raw, schema=None):
    if not isinstance(raw, dict):
        raise ContractError("Case must be an object")
    schema = schema or raw.get("schema_version", CURRENT_SCHEMA)
    if schema not in (SCHEMA, CURRENT_SCHEMA):
        raise ContractError("Unsupported case schema")
    if raw.get("schema_version", schema) != schema:
        raise ContractError("Case and run schema differ")
    identifier(raw.get("case_id"))
    company = raw.get("company")
    if not isinstance(company, dict):
        raise ContractError("Company must be an object")
    identifier(company.get("company_id"))
    if not isinstance(company.get("name"), str) or not company["name"].strip():
        raise ContractError("Company name is required")
    provenance = company.get("provenance", {})
    if not isinstance(provenance, dict):
        raise ContractError("Provenance must be an object")
    for field in FIELDS:
        if field not in company:
            continue
        value = company[field]
        if field in ("name", "legal_name"):
            valid = isinstance(value, str) and bool(value.strip())
        else:
            valid = isinstance(value, list) and all(isinstance(v, str) for v in value)
        if not valid:
            raise ContractError(f"Invalid company field: {field}")
        p = provenance.get(field)
        if not isinstance(p, dict) or not isinstance(p.get("source"), str) or not p["source"]:
            raise ContractError(f"Missing provenance: {field}")
        if schema == SCHEMA:
            if type(p.get("website_derived")) is not bool or "dependence" in p:
                raise ContractError(f"Invalid legacy dependence flag: {field}")
        elif (
            p.get("dependence") not in ("independent", "website_derived", "unknown")
            or "website_derived" in p
        ):
            raise ContractError(f"Explicit dependence required: {field}")
        date = p.get("observed_at")
        if date is not None:
            try:
                datetime.fromisoformat(date)
            except (ValueError, TypeError) as exc:
                raise ContractError("Invalid provenance date") from exc
    url = normalize_url(raw.get("candidate_url"))
    return {
        **raw,
        "schema_version": schema,
        "candidate_url": url,
        "candidate_domain": urlsplit(url).hostname,
        "company_snapshot_hash": digest(company),
    }


def validate_reference_label(raw, case_ids):
    """One reviewer's verdict for one case; never authoritative over a derived verdict."""
    if not isinstance(raw, dict) or set(raw) != {
        "case_id",
        "verdict",
        "reviewer",
        "origin",
        "blind",
        "rationale",
        "recorded",
        "evidence_scope",
    }:
        raise ContractError("A reference label must contain exactly its declared fields")
    if raw["case_id"] not in case_ids:
        raise ContractError("Reference label references a case outside this run")
    if raw["verdict"] not in VERDICTS:
        raise ContractError("Unknown reference verdict")
    if raw["origin"] not in REFERENCE_ORIGINS:
        raise ContractError("Unknown reference origin")
    if raw["evidence_scope"] not in EVIDENCE_SCOPES:
        raise ContractError("Unknown evidence scope")
    if type(raw["blind"]) is not bool:
        raise ContractError("Blindness must be stated explicitly")
    if raw["origin"] == "owner_review" and raw["blind"]:
        raise ContractError("A reviewed verdict cannot be blind")
    for key in ("reviewer", "rationale"):
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ContractError(f"A reference label requires {key}")
    try:
        datetime.fromisoformat(raw["recorded"])
    except (ValueError, TypeError) as exc:
        raise ContractError("Invalid reference label date") from exc
    return dict(raw)


def blinded_company(company):
    return {
        "fields": {k: company[k] for k in FIELDS if k in company},
        "limitations": {
            k: {
                **(
                    {"dependence": v["dependence"]}
                    if "dependence" in v
                    else {"website_derived": v["website_derived"]}
                ),
                "observed_at": v.get("observed_at"),
            }
            for k, v in company["provenance"].items()
            if k in FIELDS
        },
    }


def default_config():
    return {
        "schema_version": CURRENT_SCHEMA,
        "rubric_version": "rubric-v3",
        "relationship_policy_version": "evidence-directional-v1",
        "decision_version": "decision-v2",
        "prompt_version": "none",
        "replicate_id": "initial",
        "seed": 42,
        "models": {
            "labeler_1": "gpt-5.6-luna",
            "labeler_2": "gpt-5.6-terra",
            "labeler_3": "gpt-5.6-sol",
            "judge": "gpt-5.6-sol",
        },
        "collection": {
            "version": "collector-v4",
            "pages": 3,
            "redirects": 5,
            "chain_seconds": 20,
            "target_seconds": 90,
            "body_bytes": 2 * 1024 * 1024,
            "page_chars": 30000,
            "bundle_chars": 60000,
            "page_logos": 10,
            "bundle_logos": 20,
            "retries": 1,
            "origin_interval": 1.0,
            "discovery_scope": "exact-host",
            "cache_ttl_seconds": 86400,
        },
        "concurrency": {"collection": 8, **dict.fromkeys(ROLES, 1), "judge": 2},
        "max_attempts": 2,
        "lease_seconds": 120,
        "judge_high_water": 32,
        "supplemental_rounds": 1,
        "supplemental_seconds": 30,
        "runtime": "synthetic-v1",
        "software_revision": "0.2.0",
    }


def validate_config(config):
    expected = default_config()
    if not isinstance(config, dict) or set(config) - {"runtime_options"} != set(expected):
        raise ContractError("Configuration must contain exactly the V1 configuration fields")
    if "runtime_options" in config:
        options = config["runtime_options"]
        if not isinstance(options, dict) or set(options) != {
            "timeout_seconds",
            "max_output_bytes",
            "max_concurrent",
        }:
            raise ContractError("Invalid runtime options")
        if any(type(v) is not int or v < 1 for v in options.values()):
            raise ContractError("Runtime limits must be positive integers")
    if config["schema_version"] not in (SCHEMA, CURRENT_SCHEMA):
        raise ContractError("Unsupported configuration schema")
    if not all(isinstance(config[k], dict) for k in ("models", "concurrency", "collection")):
        raise ContractError("Models, concurrency and collection must be objects")
    for key in (
        "rubric_version",
        "relationship_policy_version",
        "decision_version",
        "prompt_version",
        "replicate_id",
        "runtime",
        "software_revision",
    ):
        if not isinstance(config[key], str) or not config[key]:
            raise ContractError(f"Invalid configuration: {key}")
    if set(config["models"]) != {*ROLES, "judge"} or not all(config["models"].values()):
        raise ContractError("Four explicit model roles are required")
    if set(config["concurrency"]) != {"collection", *ROLES, "judge"}:
        raise ContractError("Invalid concurrency roles")
    for value in config["concurrency"].values():
        if type(value) is not int or not 1 <= value <= 128:
            raise ContractError("Concurrency must be between 1 and 128")
    for key in ("max_attempts", "lease_seconds", "judge_high_water", "supplemental_seconds"):
        if type(config[key]) is not int or config[key] < 1:
            raise ContractError(f"Invalid positive limit: {key}")
    if type(config["seed"]) is not int or config["supplemental_rounds"] not in (0, 1):
        raise ContractError("Invalid seed or supplemental limit")
    policy = config["collection"]
    if set(policy) != set(expected["collection"]) or policy["discovery_scope"] != "exact-host":
        raise ContractError("Unsupported collection policy")
    for key, value in policy.items():
        if key in ("version", "discovery_scope"):
            continue
        if type(value) not in (int, float) or value < 0 or not value < float("inf"):
            raise ContractError(f"Invalid collection limit: {key}")
    for key in (
        "pages",
        "redirects",
        "body_bytes",
        "page_chars",
        "bundle_chars",
        "page_logos",
        "bundle_logos",
        "retries",
    ):
        if type(policy[key]) is not int:
            raise ContractError(f"Collection limit must be an integer: {key}")
    for key in (
        "pages",
        "body_bytes",
        "page_chars",
        "bundle_chars",
        "chain_seconds",
        "target_seconds",
    ):
        if policy[key] <= 0:
            raise ContractError(f"Collection limit must be positive: {key}")
    if policy["pages"] > 3 or policy["retries"] > 1 or policy["redirects"] > 5:
        raise ContractError("V1 collection caps exceeded")
    if policy["version"] not in ("collector-v1", "collector-v2", "collector-v3", "collector-v4"):
        raise ContractError("Unsupported collector version")
    if config["rubric_version"] not in ("rubric-v1", "rubric-v2", "rubric-v3"):
        raise ContractError("Unsupported rubric")
    if config["schema_version"] == SCHEMA and config["rubric_version"] != "rubric-v1":
        raise ContractError("Legacy schema requires its original rubric")
    if config["decision_version"] not in ("none", "decision-v1", "decision-v2"):
        raise ContractError("Unsupported decision revision")
    directional = config["relationship_policy_version"] == "evidence-directional-v1"
    if config["relationship_policy_version"] not in ("conservative-v1", "evidence-directional-v1"):
        raise ContractError("Unsupported relationship policy")
    if directional != (config["rubric_version"] == "rubric-v3"):
        raise ContractError("The evidence-directional policy requires rubric-v3")
    if directional != (config["decision_version"] != "none"):
        raise ContractError("A derived verdict requires the evidence-directional policy")
    if config["runtime"] == "codex-subscription-v1":
        expected_prompt = {
            (SCHEMA, "rubric-v1"): "codex-evidence-v1",
            (CURRENT_SCHEMA, "rubric-v1"): "codex-evidence-v2",
            (CURRENT_SCHEMA, "rubric-v2"): "codex-evidence-v3",
            (CURRENT_SCHEMA, "rubric-v3"): "codex-evidence-v4",
        }[(config["schema_version"], config["rubric_version"])]
        if config["prompt_version"] != expected_prompt:
            raise ContractError("Prompt, rubric and run schema differ")
    canonical(config)
    return config

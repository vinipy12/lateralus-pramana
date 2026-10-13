"""Usage normalization and explicit, assumption-driven cost calculations."""

from decimal import Decimal

COUNTERS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def unavailable_usage(reason="runtime_does_not_expose_usage"):
    return {
        "usage_status": "unavailable",
        "source": "unknown",
        "missing_reason": reason,
        **dict.fromkeys(COUNTERS),
        "cached_in_input": None,
        "reasoning_in_output": None,
        "estimate": None,
        "native_payload_ref": None,
    }


def validate_usage(usage):
    if not isinstance(usage, dict) or usage.get("usage_status") not in (
        "reported",
        "partial",
        "estimated",
        "unavailable",
    ):
        raise ValueError("Invalid usage status")
    for key in COUNTERS:
        value = usage.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Usage counters must be nonnegative integers or null")
    if usage.get("cached_in_input") is True:
        a, b = usage.get("input_tokens"), usage.get("cached_input_tokens")
        if a is not None and b is not None and b > a:
            raise ValueError("Cached tokens exceed total input")
    if usage.get("reasoning_in_output") is True:
        a, b = usage.get("output_tokens"), usage.get("reasoning_tokens")
        if a is not None and b is not None and b > a:
            raise ValueError("Reasoning tokens exceed total output")
    if usage["usage_status"] in ("unavailable", "estimated") and any(
        usage.get(k) is not None for k in COUNTERS
    ):
        raise ValueError("Estimates belong in the separate estimate field")
    return usage


def api_equivalent_cost(usage, prices):
    validate_usage(usage)
    if usage["usage_status"] not in ("reported", "partial"):
        return None
    if usage.get("cached_in_input") is not True or usage.get("reasoning_in_output") is not True:
        return None
    fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    if any(usage.get(k) is None for k in fields):
        return None
    for key in ("version", "effective_date", "source_url", "currency", "model", "provider"):
        if not prices.get(key):
            raise ValueError(f"Price provenance missing: {key}")
    rates = [
        Decimal(str(prices[k]))
        for k in ("input_per_million", "cached_per_million", "output_per_million")
    ]
    if any(not r.is_finite() or r < 0 for r in rates):
        raise ValueError("Invalid price rate")
    i, c, o = (usage[k] for k in fields)
    return ((i - c) * rates[0] + c * rates[1] + o * rates[2]) / Decimal(1_000_000)


def production_scenario(
    *,
    targets,
    cases,
    cache_hit,
    review_fraction,
    collection_cost,
    cache_read_cost,
    rule_cost,
    agent_review_cost,
    storage_cost,
):
    values = (
        targets,
        cases,
        collection_cost,
        cache_read_cost,
        rule_cost,
        agent_review_cost,
        storage_cost,
    )
    if any(v < 0 for v in values) or not 0 <= cache_hit <= 1 or not 0 <= review_fraction <= 1:
        raise ValueError("Invalid scenario assumptions")
    deterministic = (
        targets * ((1 - cache_hit) * collection_cost + cache_hit * cache_read_cost)
        + cases * rule_cost
        + storage_cost
    )
    return {
        "deterministic": deterministic,
        "hybrid": deterministic + cases * review_fraction * agent_review_cost,
        "full_agent": deterministic - cases * rule_cost + cases * agent_review_cost,
        "initial_full_pipeline_labels": 3 * cases,
        "initial_full_pipeline_judges": cases,
    }

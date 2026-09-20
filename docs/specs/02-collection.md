# Deterministic evidence collection

Status: proposed v1 contract. Related: [measurement](04-measurement.md), [delivery](06-delivery.md).

## Input and identities

`CompanyIdentity` contains `company_id`, `name`, optional `legal_name`, aliases, descriptions, locations, phones, social URLs, and per-field provenance: source, observed date when known, and whether the field was derived from the candidate website. Missing fields remain missing, not inferred.

`Case` contains `case_id`, an immutable company-identity snapshot ID, `candidate_url`, normalized candidate domain, source record reference, sampling stratum, and optional synthetic-generation metadata. Source labels and synthetic flags are evaluator-only and are withheld from labelers and the judge.

Cases are assessed individually. Website collection can be shared across cases, but labels cannot be shared merely because domains match. Stable IDs must not disclose company names or reference-label provenance to agents unintentionally.

## Proposed collection limits

All limits live in the experiment manifest; they are starting values to test, not hidden constants.

| Limit | Proposed default |
|---|---|
| Pages | Homepage plus at most one About and one Contact page |
| Redirects | 5 followed hops per request chain |
| Time | 20 seconds per request chain, 90 seconds total initial collection per target |
| Body | 2 MiB decompressed bytes per page; enforce while streaming |
| Extraction | 30,000 Unicode characters per page, 60,000 per bundle |
| Retries | At most 1 retry per eligible failed request; bounded by remaining target budget |
| Concurrency | 8 global requests; 1 request per origin; at least 1 second between starts per origin |
| Supplemental collection | At most 1 round, 1 page, 30 seconds per case |

Robots requests, retries, alternate schemes/hosts, and redirects consume the overall time/request budget and are recorded. Honor applicable robots directives and Retry-After within the cap; otherwise defer or mark policy-blocked. Never keep retrying to obtain a decisive label.

## Fetch policy

Prefer supplied explicit URLs; otherwise try HTTPS at the normalized hostname. A configured HTTP fallback is allowed only after a qualifying connection failure, not to conceal TLS validation errors. Optional `www` fallback has deterministic ordering, recorded reasons, and stays within the same budget.

Follow HTTP redirects explicitly and record each hop. Different registrable domains are evidence, not automatic mismatches. Detect loops. Record HTML refresh targets as evidence; v1 does not follow refresh or execute JavaScript. Secondary-page discovery is restricted to the final website's registrable domain. Pick links by versioned About/Contact patterns, deterministic ranking, and a stable URL tie-breaker. Never use a search engine or model during collection.

Fetch only public HTTP(S) destinations. Reject URL credentials, unsupported ports outside the configured allowlist, localhost, private/link-local/reserved addresses, and cloud metadata endpoints. Revalidate DNS and destination addresses on every redirect and connection; guard against DNS rebinding. Do not carry credentials, cookies, or authorization headers across origins. These controls apply equally to judge-requested URLs.

Record fetch failure independently from identity assessment. DNS failure, 403, 429, unsupported media, and JavaScript-only content must not become identity mismatches by default.

## Extraction

For supported HTML, deterministically extract title, description, canonical URL, headings, bounded main/body text, organization structured data, footer identity/copyright text, phone/address candidates, social profile links, About/Contact links, and parking indicators. Retain visible evidence of conflicts rather than collapsing to one identity.

Each retained item has `element_id`, page ID, type, original text/value, normalized value when applicable, document location (selector or structured-data path), and text offsets where applicable. Count examined, retained, dropped, and truncated elements by type; counts describe the extractor's rules, not an abstract claim about every DOM element.

Exclude scripts/styles from visible text. Structured data is parsed as data, never executed. Version normalization, language-specific patterns, parser, public-suffix data, and parking-indicator lists. Parking claims need evidence; a bare keyword is insufficient.

## Artifact contract

- `FetchAttempt`: target, request/chain IDs, URL, ordered hops with status and timing, resolved public destination metadata, timestamps, duration, response headers allowlist, observed/downloaded bytes, content type, body hash, retry reason, and outcome.
- `PageEvidence`: fetch reference, requested/final URLs, retained elements, extraction counts, parser version, body artifact reference, and truncation/unsupported-content flags.
- `EvidenceBundle`: schema version, bundle ID/content hash, target ID, collection configuration hash, ordered page references, observed time range, collection outcome, and optional predecessor bundle ID.
- `CaseEvidence`: case ID, company snapshot hash, evidence bundle ID, and any deliberately excluded fields with reasons.

IDs and hashes use a documented canonical serialization. Re-extraction from identical stored bytes and configuration must reproduce the same content, ordering, and evidence IDs; volatile acquisition timestamps live outside the deterministic extraction payload. Live network collection is not reproducible merely because the collector has no LLM.

## Cache and storage

Cache by normalized fetch target plus collection-policy/version key. Do not merge unrelated paths or erase URL path/query semantics to improve cache hits. Track requested and final targets separately; cross-domain redirects do not merge company identities.

A pilot may reuse a snapshot for 24 hours; pinned benchmark snapshots remain immutable regardless of cache age. Expired cache entries trigger new bundles, never mutation. Shared fetch cost belongs to one collection event and is allocated across case references only for reporting.

Store artifacts outside the repository in a consumer-controlled private directory; a Git-ignored directory inside the checkout is not an adequate data boundary. Proposed raw-body retention is 30 days for exploratory runs; benchmark-selected evidence is retained until the experiment is retired. Record purges and any lost replay capability. Apply access restrictions to raw content and source records; redact secrets from URLs/logs and retain only relevant business identifiers in agent inputs. Treat source references, telemetry containing URLs, and agent outputs as consumer data too. Do not transfer artifacts between consumers or use a shared cross-consumer cache. Keep any runtime index in the same consumer-controlled storage boundary.

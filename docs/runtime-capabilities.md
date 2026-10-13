# Runtime capabilities

## Codex subscription adapter

`codex-subscription-v1` launches the installed Codex CLI using its existing ChatGPT login. It uses `codex exec`, with one fresh ephemeral session per case, role and round. It does not read or copy credential files, set an API key, resume another assessor's context, or fall back to API-key authentication.

This uses the supported [non-interactive CLI](https://learn.chatgpt.com/docs/non-interactive-mode) and [ChatGPT authentication](https://learn.chatgpt.com/docs/auth) paths. Subscription rate and usage limits still apply; the local process limit is not evidence of unlimited account capacity.

The adapter was verified with Codex CLI 0.155.1. It accepts the 0.155.x line; a different minor version requires validating its flags and event contracts first. Runtime limits are included in the immutable run configuration: 180 seconds per invocation, 4 MiB captured output, and five local process slots by default. The standard lineup remains Luna/Terra/Sol for the three labelers, and Sol for the separate judge.

## Commands

Use a supported SQLite runtime as described in the [implementation guide](implementation.md).

```sh
PYTHONPATH=src python -m pramana preflight --runtime codex-subscription-v1
PYTHONPATH=src python -m pramana codex-smoke --run subscription-smoke --cases 1
PYTHONPATH=src python -m pramana config --runtime codex-subscription-v1 > .local/codex-config.json
```

`codex-smoke` sends only generated synthetic company/evidence data to real subscription-backed assessors. It accepts one to five cases, uses one attempt per role, and disables supplemental rounds. A one-case test uses three labeler sessions and one judge session. Repeating a completed run does not launch new model sessions.

For an authorized real manifest:

```sh
PYTHONPATH=src python -m pramana --consumer consumer_a import .local/cases.jsonl --config .local/codex-config.json --run run_a
PYTHONPATH=src python -m pramana --consumer consumer_a run --run run_a --allow-network --allow-codex
```

`--allow-network` authorizes website collection; `--allow-codex` authorizes disclosure of the selected case evidence to Codex. Import alone does neither. An authorized private 100-case manifest was subsequently run; see [V0 findings](v0-findings.md) for the partial outcome and limitations.

## Execution boundary

The adapter ignores ordinary user configuration for these assessment sessions while retaining the existing login and managed requirements. API-key/provider environment overrides and inherited parent-session routing variables are removed. `forced_login_method=chatgpt` and `model_provider=openai` prevent accidental API-key fallback.

Each session starts outside the checkout in an empty temporary working directory, with a read-only sandbox. Shell, browser, computer-use, connector, plugin, image, memory and subagent features are disabled, web search is disabled, and repository/skill instructions are not injected. It does not bypass sandboxing or hook trust. The remaining built-in tool surface is not claimed to be empty: the versioned prompt forbids tool use, and observable command, MCP, web-search and file-change events reject the assessment and stop admission. Read-only sandboxing remains the filesystem mutation boundary.

The default `codex-evidence-v3` prompt implements `rubric-v2` (identity plus a second supplied identifier) and the unchanged `conservative-v1` relationship policy. It treats every evidence field and peer assessment as untrusted data. It asks for passage selections with host-attached exact citations, a short rationale and uncertainty where appropriate; it does not ask for hidden reasoning. The judge sees anonymized assessment content in three named slots; the host attaches the underlying label IDs. The legacy `codex-evidence-v1` and `codex-evidence-v2` prompts remain available with `rubric-v1` for older configurations. Acquisition logs, source references, raw body paths and evaluator sample metadata are excluded from model inputs.

Inputs, output schemas, JSONL events, stderr and final receipts are stored under the selected consumer's `codex-invocations/` directory. Session files are ephemeral; Codex still uses its normal local authentication and internal state infrastructure. Do not override `sqlite_home` per invocation: the startup experiment found that creating fresh CLI state databases prevented session startup within the time budget. Generated state caches from that failed experiment were removed; failure receipts remain.

## Measured capability evidence

The live one-case synthetic probe completed successfully:

- Three distinct, concurrent Codex labeler sessions requested Luna, Terra and Sol.
- A fourth, fresh Sol judge session received all three anonymous labels and returned a valid adjudication.
- All four outputs passed Pramana's structural, lineage and citation validation.
- All four sessions reported input, cached-input and output token counters.
- No observed command, MCP, web-search or file-change events occurred.

The earlier two-case startup attempt timed out in three CLI processes before any `thread.started` event. Those attempts remain execution-unknown with unknown usage; they are not reported as free or silently retried. The successful one-case diagnostic is a separate run.

The JSONL stream does not independently attest the actual backend model identity, so Pramana records the requested model and leaves actual identity null. Reasoning tokens, provider totals, billing inclusion semantics and complete monetary cost remain unknown. Raw reported counters are preserved with `usage_status=partial`.

The subsequent corrected pilot recorded 361 distinct ChatGPT-authenticated sessions, 59 valid adjudications, and 41 incomplete cases. All usage records remained partial. See [V0 findings](v0-findings.md) for collection and citation failures, including the separate cancelled run. Offline tests also cover judge/labeler overlap and two-judge concurrency. These experiments establish session integration, not reference-label accuracy, adversarial robustness, account quotas, or production throughput.

The post-V0 10-case development canary exercised `codex-evidence-v2` in 24 distinct subscription sessions. All six evidence-bearing cases produced valid adjudications with host-attached citations; four empty bundles skipped assessment. Five provisional verified-domain outputs were exported. No assessment outputs were rejected. See [recorded refactor verification](implementation.md#refactor-verification-recorded-on-2026-09-21) for usage and limitations. This small canary does not establish semantic accuracy.

## Failure and recovery

Timeouts, invalid final files, provider/auth/quota failures and forbidden tool events preserve private session artifacts and any reported usage. They quarantine the attempt and stop further admissions, rather than launching failing sessions over the rest of the dataset. Cancellation terminates the process group and records a receipt. Plain resume never redispatches execution-unknown jobs; `--retry-unknown` is an explicit operator decision that may consume additional subscription usage.

Automatic external invocation reconciliation remains unavailable for ephemeral sessions. Local receipts provide diagnostic evidence; the storage layer can retain late reported usage without accepting a stale assessment.

## Offline adapter

`SyntheticRuntime` remains available for zero-model-call testing. It always returns uncertain and explicitly records that it performed no identity assessment. The offline suite covers independent streams, overlapping judges, supplemental rounds, duplicate completion, stale leases, cancellation and cache isolation. Adapter tests use a fake executable to verify subscription-only environment handling, fresh sessions, usage preservation, timeout termination and rejected tool actions.

The stricter prompt and rubric subsequently ran on the same 10 development cases in a separate live canary: 4 matches with explicit corroboration, 1 uncertain, 1 mismatch, and 4 not assessed. All 24 subscription sessions produced valid assessment outputs; no calls were spent on empty bundles. One prior match became uncertain in the new run because a second identifier was unconfirmed. Seven unexpired evidence bundles were reused and three targets were recollected. Historical verdicts were preserved; results remain provisional and do not establish accuracy.

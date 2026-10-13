"""Private local experiment CLI. Live collection is explicit; models are adapters."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .agents import SyntheticRuntime, preflight
from .codex_runtime import RUNTIME, CodexRuntime, subscription_config
from .collection import Collector, SyntheticCollector
from .contracts import default_config
from .orchestration import Pipeline
from .reporting import export, summary
from .review import review_packets
from .storage import Store


def synthetic_cases(count):
    for i in range(count):
        yield {
            "case_id": f"case_{i:08d}",
            "company": {
                "company_id": f"company_{i:08d}",
                "name": f"Example Workshop {i}",
                "provenance": {
                    "name": {
                        "source": "synthetic_fixture",
                        "observed_at": None,
                        "dependence": "independent",
                    }
                },
            },
            "candidate_url": f"https://example-{i // 2}.test/",
            "stratum": "synthetic",
            "synthetic": True,
            "source_record_reference": f"synthetic_{i}",
        }


def jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            if len(line) > 1024 * 1024:
                raise ValueError(f"Input line {line_number} exceeds the 1 MiB case limit")
            try:
                yield json.loads(line)
            except ValueError as exc:
                raise ValueError(f"Invalid JSON at line {line_number}") from exc


def parser():
    p = argparse.ArgumentParser(prog="pramana", description=__doc__)
    p.add_argument("--runtime-root", default=".local", help="Consumer-controlled runtime root")
    p.add_argument("--consumer", default="synthetic", help="Opaque consumer identifier")
    commands = p.add_subparsers(dest="command", required=True)
    config_parser = commands.add_parser("config", help="Print a versioned run configuration")
    config_parser.add_argument(
        "--runtime", choices=("synthetic-v1", RUNTIME), default="synthetic-v1"
    )
    preflight_parser = commands.add_parser(
        "preflight", help="Report installed runtime capabilities"
    )
    preflight_parser.add_argument(
        "--runtime", choices=("synthetic-v1", RUNTIME), default="synthetic-v1"
    )
    smoke = commands.add_parser("smoke", help="Run an entirely synthetic offline experiment")
    smoke.add_argument("--run", default="smoke")
    smoke.add_argument("--cases", type=int, default=12)
    codex_smoke = commands.add_parser(
        "codex-smoke", help="Use ChatGPT subscription sessions on synthetic evidence"
    )
    codex_smoke.add_argument("--run", default="codex-smoke")
    codex_smoke.add_argument("--cases", type=int, default=2)
    packets = commands.add_parser(
        "review-packet", help="Write blind review packets for a collected run"
    )
    packets.add_argument("--run", required=True)
    packets.add_argument("--reviewer", required=True)
    reference = commands.add_parser(
        "reference-import", help="Append independently produced labels for an existing run"
    )
    reference.add_argument("manifest")
    reference.add_argument("--run", required=True)
    imp = commands.add_parser("import", help="Freeze a provider-neutral JSONL manifest")
    imp.add_argument("manifest")
    imp.add_argument("--run", required=True)
    imp.add_argument("--config", required=True)
    for name in ("run", "resume", "collect", "report", "status", "verify", "cancel"):
        child = commands.add_parser(name)
        child.add_argument("--run", required=True)
        if name in ("run", "resume", "collect"):
            child.add_argument(
                "--allow-network",
                action="store_true",
                help="Explicitly authorize public website requests",
            )
            child.add_argument(
                "--retry-unknown",
                action="store_true",
                help="Explicitly allow another attempt after unknown external execution",
            )
            child.add_argument(
                "--allow-codex",
                action="store_true",
                help="Authorize case evidence disclosure to subscription-backed Codex sessions",
            )
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "config":
        print(
            json.dumps(
                subscription_config() if args.runtime == RUNTIME else default_config(), indent=2
            )
        )
        return 0
    if args.command == "preflight" and args.runtime == "synthetic-v1":
        print(json.dumps(preflight(SyntheticRuntime(), default_config()), indent=2))
        return 0
    if args.command == "smoke" and args.cases < 0:
        raise SystemExit("Case count cannot be negative")
    if args.command == "codex-smoke" and not 1 <= args.cases <= 5:
        raise SystemExit("Codex smoke runs accept 1–5 synthetic cases")
    store = None
    try:
        store = Store(args.runtime_root, args.consumer)
        if args.command == "preflight":
            runtime = CodexRuntime(store.root)
            print(json.dumps(preflight(runtime, subscription_config()), indent=2))
        elif args.command == "codex-smoke":
            config = subscription_config()
            config.update(max_attempts=1, supplemental_rounds=0)
            store.import_cases(args.run, synthetic_cases(args.cases), config)
            runtime = CodexRuntime(store.root, config["runtime_options"])
            state = asyncio.run(
                Pipeline(
                    store, SyntheticCollector(store.artifacts, config["collection"]), runtime
                ).run(args.run)
            )
            report, path = export(store, args.run)
            print(
                json.dumps(
                    {
                        "state": state,
                        "completed_cases": report["completed_cases"],
                        "report_directory": str(path),
                        "evidence": "synthetic",
                        "assessors": "codex_subscription",
                    }
                )
            )
        elif args.command == "review-packet":
            root, count = review_packets(store, args.run, args.reviewer)
            print(json.dumps({"packets": count, "review_directory": str(root)}))
        elif args.command == "reference-import":
            print(json.dumps(store.import_reference_labels(args.run, jsonl(args.manifest))))
        elif args.command == "import":
            config = json.loads(Path(args.config).read_text())
            count = store.import_cases(args.run, jsonl(args.manifest), config)
            print(json.dumps({"accepted_cases": count, "run": args.run}))
        elif args.command == "smoke":
            store.import_cases(args.run, synthetic_cases(args.cases), default_config())
            collector = SyntheticCollector(store.artifacts, default_config()["collection"])
            asyncio.run(Pipeline(store, collector, SyntheticRuntime()).run(args.run))
            report, path = export(store, args.run)
            print(
                json.dumps(
                    {
                        "state": report["state"],
                        "completed_cases": report["completed_cases"],
                        "report_directory": str(path),
                    }
                )
            )
        elif args.command in ("run", "resume", "collect"):
            config = store.run(args.run)["config"]
            runtime = SyntheticRuntime()
            if config["runtime"] == RUNTIME and args.command != "collect":
                if not args.allow_codex:
                    raise ValueError("Subscription labeling requires --allow-codex")
                runtime = CodexRuntime(store.root, config.get("runtime_options"))
            if args.command == "resume":
                store.resume(args.run)
            if args.retry_unknown:
                store.retry_unknown(args.run)
            if config["runtime"] == "synthetic-v1":
                # Never run fake assessors over real consumer inputs via this CLI.
                for row in store.db.execute("SELECT snapshot FROM cases WHERE run=?", (args.run,)):
                    if store.artifacts.get_json(row[0]).get("synthetic") is not True:
                        raise ValueError(
                            "Synthetic execution requires explicitly synthetic input cases"
                        )
                collector = SyntheticCollector(store.artifacts, config["collection"])
            else:
                if not args.allow_network:
                    raise ValueError("Live collection requires --allow-network")
                if args.command != "collect" and config["runtime"] != RUNTIME:
                    raise ValueError(
                        "No live agent adapter installed; use collect and integrate the Runtime protocol"
                    )
                collector = Collector(
                    store.artifacts,
                    config["collection"],
                    concurrency=config["concurrency"]["collection"],
                )
            state = asyncio.run(
                Pipeline(store, collector, runtime).run(
                    args.run, collect_only=args.command == "collect"
                )
            )
            print(json.dumps({"state": state}))
        elif args.command == "report":
            report, path = export(store, args.run)
            print(json.dumps({"state": report["state"], "report_directory": str(path)}))
        elif args.command == "status":
            print(json.dumps(summary(store, args.run), indent=2))
        elif args.command == "verify":
            store.verify(args.run)
            print(json.dumps({"integrity": "ok"}))
        elif args.command == "cancel":
            store.cancel(args.run)
            print(json.dumps({"state": "cancelled"}))
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"pramana: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("pramana: interrupted; durable attempts retained for resume", file=sys.stderr)
        return 130
    finally:
        if store is not None:
            store.close()

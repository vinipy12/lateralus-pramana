"""SQLite transactional pilot backend. All async access uses one writer executor."""

import asyncio
import json
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial

from .artifacts import ArtifactStore, consumer_root
from .contracts import (
    ROLES,
    blinded_company,
    canonical,
    digest,
    identifier,
    utcnow,
    validate_case,
    validate_config,
    validate_reference_label,
)
from .measurement import unavailable_usage, validate_usage
from .validation import validate_assessment
from .workflow import admission, judge_ready, supplemental_changed, supplemental_target

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(version INTEGER NOT NULL);
INSERT INTO meta SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM meta);
CREATE TABLE IF NOT EXISTS runs(
 id TEXT PRIMARY KEY, config TEXT NOT NULL, config_hash TEXT NOT NULL, state TEXT NOT NULL,
 created TEXT NOT NULL, barrier TEXT, manifest_hash TEXT, ended TEXT);
CREATE TABLE IF NOT EXISTS cases(
 run TEXT NOT NULL REFERENCES runs(id), id TEXT NOT NULL, snapshot TEXT NOT NULL,
 target TEXT NOT NULL, current_round INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'collecting', final TEXT, PRIMARY KEY(run,id));
CREATE INDEX IF NOT EXISTS cases_target ON cases(run,target,id);
CREATE INDEX IF NOT EXISTS cases_state ON cases(run,state,id);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, run TEXT NOT NULL REFERENCES runs(id), case_id TEXT,
 role TEXT NOT NULL, round INTEGER NOT NULL, target TEXT, bundle TEXT,
 state TEXT NOT NULL DEFAULT 'pending', fence INTEGER NOT NULL DEFAULT 0,
 owner TEXT, expires REAL, result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 created REAL NOT NULL, eligible REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS claim_jobs ON jobs(run,role,state,created,id,eligible);
CREATE INDEX IF NOT EXISTS lease_jobs ON jobs(state,expires);
CREATE INDEX IF NOT EXISTS row_jobs ON jobs(run,case_id,round,role,state);
CREATE TABLE IF NOT EXISTS targets(
 run TEXT NOT NULL REFERENCES runs(id), url TEXT NOT NULL, job TEXT NOT NULL REFERENCES jobs(id),
 PRIMARY KEY(run,url));
CREATE TABLE IF NOT EXISTS rounds(
 run TEXT NOT NULL, case_id TEXT NOT NULL, round INTEGER NOT NULL, bundle TEXT NOT NULL,
 PRIMARY KEY(run,case_id,round), FOREIGN KEY(run,case_id) REFERENCES cases(run,id));
CREATE TABLE IF NOT EXISTS labels(
 run TEXT NOT NULL, case_id TEXT NOT NULL, round INTEGER NOT NULL, role TEXT NOT NULL,
 artifact TEXT NOT NULL, assessment TEXT NOT NULL,
 PRIMARY KEY(run,case_id,round,role), FOREIGN KEY(run,case_id,round) REFERENCES rounds(run,case_id,round));
CREATE TABLE IF NOT EXISTS attempts(
 id TEXT PRIMARY KEY, job TEXT NOT NULL REFERENCES jobs(id), fence INTEGER NOT NULL,
 started TEXT NOT NULL, invocation TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS receipts(
 attempt TEXT PRIMARY KEY REFERENCES attempts(id), outcome TEXT NOT NULL,
 artifact TEXT, usage TEXT NOT NULL, duration_ms REAL, finished TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reconciliations(
 attempt TEXT PRIMARY KEY REFERENCES attempts(id), usage TEXT NOT NULL, artifact TEXT,
 recorded TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
 seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL REFERENCES runs(id),
 payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS event_run ON events(run,seq);
CREATE TABLE IF NOT EXISTS reference_labels(
 run TEXT NOT NULL REFERENCES runs(id), case_id TEXT NOT NULL, reviewer TEXT NOT NULL,
 sequence INTEGER NOT NULL, artifact TEXT NOT NULL, verdict TEXT NOT NULL,
 origin TEXT NOT NULL, blind INTEGER NOT NULL, recorded TEXT NOT NULL, evidence_scope TEXT,
 PRIMARY KEY(run,case_id,reviewer,sequence), FOREIGN KEY(run,case_id) REFERENCES cases(run,id));
CREATE TABLE IF NOT EXISTS cache(
 key TEXT PRIMARY KEY, bundle TEXT NOT NULL, expires REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_labels_update BEFORE UPDATE ON labels BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_reference_update BEFORE UPDATE ON reference_labels BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_receipts_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER IF NOT EXISTS immutable_attempts_update BEFORE UPDATE ON attempts BEGIN SELECT RAISE(ABORT,'immutable'); END;
"""


def sqlite_supported(version):
    return (
        version >= (3, 51, 3)
        or (3, 50, 7) <= version < (3, 51, 0)
        or (3, 44, 6) <= version < (3, 45, 0)
    )


class Store:
    def __init__(self, root, consumer):
        if not sqlite_supported(sqlite3.sqlite_version_info):
            raise RuntimeError(
                f"SQLite {sqlite3.sqlite_version} lacks the WAL-reset fix; use >=3.51.3 or patched 3.50.7/3.44.6"
            )
        self.consumer = identifier(consumer)
        self.root = consumer_root(root, consumer)
        self.artifacts = ArtifactStore(self.root)
        path = self.root / "state.sqlite3"
        if path.is_symlink():
            raise ValueError("Database symlinks are forbidden")
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5, check_same_thread=False)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA_SQL)
        # Additive column; rows written before evidence scope existed keep a null scope
        # rather than being assigned one they never declared.
        if "evidence_scope" not in {
            row["name"] for row in self.db.execute("PRAGMA table_info(reference_labels)")
        }:
            self.db.execute("ALTER TABLE reference_labels ADD COLUMN evidence_scope TEXT")
        if self.db.execute("SELECT version FROM meta").fetchone()[0] != 1:
            raise RuntimeError("Unsupported storage schema; explicit migration required")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pramana-store")

    async def call(self, name, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, partial(getattr(self, name), *args, **kwargs)
        )

    def close(self):
        self.executor.shutdown(wait=True)
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, run, stage, outcome, *, job=None, attempt=None, case=None, **fields):
        config = self.run(run)
        payload = {
            "schema_version": "pramana.v1",
            "event_id": uuid.uuid4().hex,
            "experiment_id": run,
            "case_id": case,
            "target_id": fields.pop("target_id", None),
            "stage": stage,
            "logical_work_id": job,
            "attempt_id": attempt,
            "parent_event_id": None,
            "timestamp": utcnow(),
            "outcome": outcome,
            "configuration_hash": config["config_hash"],
            "software_revision": config["config"]["software_revision"],
            **fields,
        }
        self.db.execute(
            "INSERT INTO events(run,payload) VALUES(?,?)", (run, canonical(payload).decode())
        )

    def run(self, run):
        row = self.db.execute("SELECT * FROM runs WHERE id=?", (run,)).fetchone()
        if not row:
            raise ValueError("Unknown run")
        return {**dict(row), "config": json.loads(row["config"])}

    def add_job(self, run, role, case=None, round_id=0, target=None, bundle=None):
        config = self.run(run)["config_hash"]
        key = digest(
            {
                "consumer": self.consumer,
                "run": run,
                "config": config,
                "role": role,
                "case": case,
                "round": round_id,
                "target": target,
                "bundle": bundle,
            }
        )
        self.db.execute(
            "INSERT INTO jobs(id,run,case_id,role,round,target,bundle,created) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (key, run, case, role, round_id, target, bundle, time.time()),
        )
        return key

    def import_reference_labels(self, run, labels):
        """Append independently produced labels; they never alter a derived verdict."""
        self.run(run)
        case_ids = {row[0] for row in self.db.execute("SELECT id FROM cases WHERE run=?", (run,))}
        accepted = duplicates = 0
        for raw in labels:
            label = validate_reference_label(raw, case_ids)
            artifact = self.artifacts.put_json(label)
            with self.transaction():
                rows = self.db.execute(
                    "SELECT sequence,artifact FROM reference_labels WHERE run=? AND case_id=? AND reviewer=?",
                    (run, label["case_id"], label["reviewer"]),
                ).fetchall()
                if any(row["artifact"] == artifact for row in rows):
                    duplicates += 1
                    continue
                self.db.execute(
                    "INSERT INTO reference_labels VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        run,
                        label["case_id"],
                        label["reviewer"],
                        max((row["sequence"] for row in rows), default=0) + 1,
                        artifact,
                        label["verdict"],
                        label["origin"],
                        int(label["blind"]),
                        label["recorded"],
                        label["evidence_scope"],
                    ),
                )
                accepted += 1
            self.event(
                run,
                "reference_label",
                "recorded",
                case=label["case_id"],
                origin=label["origin"],
                blind=label["blind"],
                evidence_scope=label["evidence_scope"],
            )
        return {"accepted": accepted, "duplicates": duplicates}

    def reference_labels(self, run):
        """Every recorded label, newest sequence last; nothing is superseded in place."""
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT case_id,reviewer,sequence,verdict,origin,blind,recorded,evidence_scope"
                " FROM reference_labels"
                " WHERE run=? ORDER BY case_id,reviewer,sequence",
                (run,),
            )
        ]

    def import_cases(self, run, cases, config):
        identifier(run)
        validate_config(config)
        existing = self.db.execute(
            "SELECT config_hash,state FROM runs WHERE id=?", (run,)
        ).fetchone()
        if existing and existing["config_hash"] != digest(config):
            raise ValueError("Run configuration is immutable")
        if not existing:
            with self.transaction():
                self.db.execute(
                    "INSERT INTO runs(id,config,config_hash,state,created) VALUES(?,?,?,?,?)",
                    (run, canonical(config).decode(), digest(config), "importing", utcnow()),
                )
        import hashlib

        hasher = hashlib.sha256()
        count = 0
        for raw in cases:
            case = validate_case(raw, config["schema_version"])
            snapshot = self.artifacts.put_json(case)
            hasher.update(bytes.fromhex(snapshot))
            count += 1
            with self.transaction():
                old = self.db.execute(
                    "SELECT snapshot FROM cases WHERE run=? AND id=?", (run, case["case_id"])
                ).fetchone()
                if old and old[0] != snapshot:
                    raise ValueError("Case ID reused with different content")
                if existing and existing["state"] != "importing" and not old:
                    raise ValueError("Frozen manifest cannot gain cases")
                if not old:
                    self.db.execute(
                        "INSERT INTO cases(run,id,snapshot,target) VALUES(?,?,?,?)",
                        (run, case["case_id"], snapshot, case["candidate_url"]),
                    )
                    job = self.add_job(run, "collection", target=case["candidate_url"])
                    self.db.execute(
                        "INSERT INTO targets VALUES(?,?,?) ON CONFLICT DO NOTHING",
                        (run, case["candidate_url"], job),
                    )
        with self.transaction():
            current = self.run(run)
            if current["manifest_hash"] and current["manifest_hash"] != hasher.hexdigest():
                raise ValueError("Manifest order/content differs from frozen import")
            total = self.db.execute("SELECT count(*) FROM cases WHERE run=?", (run,)).fetchone()[0]
            if count != total:
                raise ValueError(
                    "Manifest contains duplicate case IDs or omitted prior import rows"
                )
            self.db.execute(
                "UPDATE runs SET manifest_hash=?,state=CASE WHEN state='importing' THEN ? ELSE state END WHERE id=?",
                (hasher.hexdigest(), "collecting" if count else "empty", run),
            )
            if not current["manifest_hash"]:
                self.event(
                    run,
                    "import",
                    "frozen" if count else "empty",
                    cases=count,
                    sqlite_version=sqlite3.sqlite_version,
                )
        return count

    def _verified_bundle(self, key):
        bundle = self.artifacts.get_json(key)
        if bundle.get("bundle_id") != digest({k: v for k, v in bundle.items() if k != "bundle_id"}):
            raise ValueError("Invalid bundle identity")
        for page in bundle["pages"]:
            self.artifacts.get(page["body_hash"])
        return bundle

    def claim(self, run, role, owner):
        config = self.run(run)
        if config["state"] in ("importing", "cancelled", "empty"):
            return None
        if role in (*ROLES, "judge", "supplemental") and not config["barrier"]:
            return None
        with self.transaction():
            if role in ROLES:
                backlog = self.db.execute(
                    "SELECT 1 FROM jobs WHERE run=? AND role='judge' AND state IN ('pending','running') LIMIT 1 OFFSET ?",
                    (run, config["config"]["judge_high_water"] - 1),
                ).fetchone()
                if backlog is not None:
                    return None
            order = "created,id"
            if config["config"]["schema_version"] == "pramana.v1" and role == "labeler_2":
                order = "created DESC,id DESC"
            row = self.db.execute(
                f"SELECT * FROM jobs WHERE run=? AND role=? AND state='pending' AND eligible<=? ORDER BY {order} LIMIT 1",
                (run, role, time.time()),
            ).fetchone()
            if not row:
                return None
            job = dict(row)
            job["fence"] += 1
            job["attempt_id"] = uuid.uuid4().hex
            job["invocation_id"] = uuid.uuid4().hex
            self.db.execute(
                "UPDATE jobs SET state='running',fence=?,owner=?,expires=?,attempts=attempts+1 WHERE id=?",
                (job["fence"], owner, time.time() + config["config"]["lease_seconds"], job["id"]),
            )
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?)",
                (job["attempt_id"], job["id"], job["fence"], utcnow(), job["invocation_id"]),
            )
            self.event(
                run,
                role,
                "started",
                job=job["id"],
                attempt=job["attempt_id"],
                case=job["case_id"],
                queue_ms=max(0, (time.time() - job["created"]) * 1000),
            )
        return job

    def renew(self, job):
        seconds = self.run(job["run"])["config"]["lease_seconds"]
        return (
            self.db.execute(
                "UPDATE jobs SET expires=? WHERE id=? AND fence=? AND state='running' AND expires>?",
                (time.time() + seconds, job["id"], job["fence"], time.time()),
            ).rowcount
            == 1
        )

    def task(self, job):
        config = self.run(job["run"])["config"]
        row = self.db.execute(
            "SELECT snapshot FROM cases WHERE run=? AND id=?", (job["run"], job["case_id"])
        ).fetchone()
        case = self.artifacts.get_json(row[0])
        bundle = self._verified_bundle(job["bundle"])
        task = {
            "case_id": digest({"consumer": self.consumer, "case": case["case_id"]}),
            "round_id": job["round"],
            "role": job["role"],
            "invocation_id": job["invocation_id"],
            "company_snapshot_hash": case["company_snapshot_hash"],
            "bundle_id": bundle["bundle_id"],
            "rubric_version": config["rubric_version"],
            "relationship_policy_version": config["relationship_policy_version"],
            "company": blinded_company(case["company"]),
            "bundle": bundle,
            "model": config["models"][job["role"]],
            "prompt_version": config["prompt_version"],
            "assessment_version": config["schema_version"],
        }
        if job["role"] == "judge":
            rows = self.db.execute(
                "SELECT artifact FROM labels WHERE run=? AND case_id=? AND round=? ORDER BY role",
                (job["run"], job["case_id"], job["round"]),
            ).fetchall()
            if len(rows) != 3:
                raise ValueError("Incomplete label set")
            labels = [self.artifacts.get_json(r[0]) for r in rows]
            import random

            random.Random(digest({"seed": config["seed"], "job": job["id"]})).shuffle(labels)
            # Only assessment IDs are opaque handles; roles/models/invocations stay internal.
            task["labels"] = [
                {
                    k: label[k]
                    for k in (
                        "assessment_id",
                        "verdict",
                        "reason_codes",
                        "rationale",
                        "citations",
                        "relationship",
                        "missing_evidence",
                        "conflicting_evidence",
                    )
                }
                for label in labels
            ]
            if config["schema_version"] == "pramana.v2":
                for visible, label in zip(task["labels"], labels, strict=True):
                    visible.update(
                        {
                            k: label.get(k)
                            for k in (
                                "website_page_id",
                                "verified_company_domain",
                                "verified_company_url",
                            )
                        }
                    )
            if config["rubric_version"] == "rubric-v2":
                for visible, label in zip(task["labels"], labels, strict=True):
                    visible["corroboration"] = label.get("corroboration")
            elif config["rubric_version"] == "rubric-v3":
                for visible, label in zip(task["labels"], labels, strict=True):
                    visible.update(
                        {
                            k: label.get(k)
                            for k in (
                                "site_substance",
                                "operator_identity",
                                "identifier_findings",
                                "identity_domain",
                                "identity_url",
                            )
                        }
                    )
            task["label_ids"] = [label["assessment_id"] for label in labels]
        return task

    def _fenced(self, job):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
        return (
            row
            and row["state"] == "running"
            and row["fence"] == job["fence"]
            and row["expires"] > time.time()
        )

    def receipt(self, job, outcome, artifact, usage, duration_ms):
        validate_usage(usage)
        inserted = self.db.execute(
            "INSERT INTO receipts VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING",
            (
                job["attempt_id"],
                outcome,
                artifact,
                canonical(usage).decode(),
                duration_ms,
                utcnow(),
            ),
        ).rowcount
        if inserted:
            self.event(
                job["run"],
                job["role"],
                outcome,
                job=job["id"],
                attempt=job["attempt_id"],
                case=job["case_id"],
                duration_ms=duration_ms,
                usage=usage,
                artifact=artifact,
            )
        elif usage["usage_status"] in ("reported", "partial"):
            prior = self.db.execute(
                "SELECT usage FROM receipts WHERE attempt=?", (job["attempt_id"],)
            ).fetchone()
            if json.loads(prior[0])["usage_status"] in ("unavailable", "estimated"):
                reconciled = self.db.execute(
                    "INSERT INTO reconciliations VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
                    (job["attempt_id"], canonical(usage).decode(), artifact, utcnow()),
                ).rowcount
                if reconciled:
                    self.event(
                        job["run"],
                        job["role"],
                        "usage_reconciled",
                        job=job["id"],
                        attempt=job["attempt_id"],
                        usage=usage,
                        artifact=artifact,
                    )
        return inserted

    def complete(self, job, output, usage=None, duration_ms=0):
        usage = usage or unavailable_usage()
        if job["role"] in (*ROLES, "judge"):
            output = validate_assessment(output, self.task(job))
        if job["role"] in ("collection", "supplemental"):
            if output.get("bundle_id") != digest(
                {k: v for k, v in output.items() if k != "bundle_id"}
            ):
                raise ValueError("Invalid collection bundle hash")
            if output.get("target_id") != digest(job["target"]):
                raise ValueError("Collection target mismatch")
            for page in output["pages"]:
                self.artifacts.get(page["body_hash"])
        artifact = self.artifacts.put_json(output)
        with self.transaction():
            if not self._fenced(job):
                # A late invocation may still have incurred usage; retain its receipt.
                self.receipt(job, "stale_completion", artifact, usage, duration_ms)
                return False
            self.receipt(job, "completed", artifact, usage, duration_ms)
            self.db.execute(
                "UPDATE jobs SET state='completed',result=?,expires=NULL WHERE id=?",
                (artifact, job["id"]),
            )
            role, run, case, round_id = job["role"], job["run"], job["case_id"], job["round"]
            if role == "collection":
                config = self.run(run)["config"]
                if output["outcome"] in ("available", "synthetic"):
                    key = digest(
                        {
                            "target": job["target"],
                            "policy": config["collection"],
                            "runtime": config["runtime"],
                        }
                    )
                    self.db.execute(
                        "INSERT INTO cache VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET bundle=excluded.bundle,expires=excluded.expires",
                        (key, artifact, time.time() + config["collection"]["cache_ttl_seconds"]),
                    )
            elif role in ROLES:
                self.db.execute(
                    "INSERT INTO labels VALUES(?,?,?,?,?,?)",
                    (run, case, round_id, role, artifact, output["assessment_id"]),
                )
                roles = [
                    r[0]
                    for r in self.db.execute(
                        "SELECT role FROM labels WHERE run=? AND case_id=? AND round=?",
                        (run, case, round_id),
                    )
                ]
                if judge_ready(roles):
                    self.add_job(run, "judge", case, round_id, bundle=job["bundle"])
                    self.event(run, "judge", "ready", case=case, round_id=round_id)
            elif role == "supplemental":
                predecessor = self._verified_bundle(job["bundle"])
                if self.run(run)["config"][
                    "schema_version"
                ] == "pramana.v2" and not supplemental_changed(predecessor, output):
                    judge = self.db.execute(
                        "SELECT result FROM jobs WHERE run=? AND case_id=? AND round=? AND role='judge'",
                        (run, case, round_id),
                    ).fetchone()[0]
                    self.db.execute(
                        "UPDATE cases SET state='completed',final=? WHERE run=? AND id=?",
                        (judge, run, case),
                    )
                    self.event(run, "supplemental", "no_new_evidence", case=case)
                    return True
                if self.run(run)["config"]["schema_version"] == "pramana.v2":
                    offset = len(predecessor.get("attempts", []))
                    output = {
                        **output,
                        "pages": [
                            {
                                **page,
                                **(
                                    {"fetch_attempt_index": page["fetch_attempt_index"] + offset}
                                    if "fetch_attempt_index" in page
                                    else {}
                                ),
                            }
                            for page in output["pages"]
                        ],
                        "attempts": predecessor.get("attempts", []) + output.get("attempts", []),
                        "failures": predecessor.get("failures", []) + output.get("failures", []),
                        "observed_from": predecessor["observed_from"],
                    }
                output = {
                    **output,
                    "pages": predecessor["pages"] + output["pages"],
                    "predecessor_bundle_id": predecessor["bundle_id"],
                }
                output.pop("bundle_id", None)
                output["bundle_id"] = digest(output)
                merged = self.artifacts.put_json(output)
                self._round(run, case, round_id + 1, merged)
            elif role == "judge":
                request = output.get("collection_request")
                target = self._supplemental_target(job, request) if request else None
                if target:
                    self.add_job(run, "supplemental", case, round_id, target, job["bundle"])
                    self.db.execute(
                        "UPDATE cases SET state='supplemental' WHERE run=? AND id=?", (run, case)
                    )
                else:
                    self.db.execute(
                        "UPDATE cases SET state='completed',final=? WHERE run=? AND id=?",
                        (artifact, run, case),
                    )
                    if request:
                        self.event(run, "supplemental", "policy_or_budget_exhausted", case=case)
        return True

    def _supplemental_target(self, job, request):
        return supplemental_target(
            self._verified_bundle(job["bundle"]),
            request,
            job["round"],
            self.run(job["run"])["config"],
        )

    def _round(self, run, case, round_id, bundle):
        self.db.execute(
            "INSERT INTO rounds VALUES(?,?,?,?) ON CONFLICT DO NOTHING",
            (run, case, round_id, bundle),
        )
        state = admission(self._verified_bundle(bundle), self.run(run)["config"])
        if state == "labeling":
            for role in ROLES:
                self.add_job(run, role, case, round_id, bundle=bundle)
        else:
            self.event(
                run,
                "assessment",
                "not_assessed",
                case=case,
                reason="no_usable_evidence",
                bundle=bundle,
            )
        self.db.execute(
            "UPDATE cases SET state=?,current_round=? WHERE run=? AND id=?",
            (state, round_id, run, case),
        )

    def release_barrier(self, run):
        with self.transaction():
            current = self.run(run)
            if current["state"] in ("cancelled", "importing", "empty"):
                return False
            pending = self.db.execute(
                "SELECT count(*) FROM jobs WHERE run=? AND role='collection' AND state NOT IN ('completed','failed')",
                (run,),
            ).fetchone()[0]
            if pending:
                return False
            if not current["barrier"]:
                totals = {
                    r[0]: r[1]
                    for r in self.db.execute(
                        "SELECT state,count(*) FROM jobs WHERE run=? AND role='collection' GROUP BY state",
                        (run,),
                    )
                }
                receipt = self.artifacts.put_json(
                    {"run": run, "totals": totals, "released_at": utcnow()}
                )
                self.db.execute(
                    "UPDATE runs SET barrier=?,state='labeling' WHERE id=?", (receipt, run)
                )
                self.event(run, "collection", "barrier_released", totals=totals, receipt=receipt)
        # Bounded, restartable admission after the durable barrier. No external calls yet.
        while True:
            rows = self.db.execute(
                "SELECT c.id,j.result,j.state FROM cases c JOIN targets t ON t.run=c.run AND t.url=c.target JOIN jobs j ON j.id=t.job WHERE c.run=? AND c.state='collecting' ORDER BY c.id LIMIT 100",
                (run,),
            ).fetchall()
            if not rows:
                break
            with self.transaction():
                for row in rows:
                    try:
                        if row["state"] != "completed":
                            raise ValueError("Collection failed internally")
                        self._verified_bundle(row["result"])
                    except (ValueError, OSError):
                        self.db.execute(
                            "UPDATE cases SET state='incomplete' WHERE run=? AND id=?",
                            (run, row["id"]),
                        )
                    else:
                        self._round(run, row["id"], 0, row["result"])
        return True

    def fail(self, job, outcome, usage=None, duration_ms=0, raw=None):
        artifact = self.artifacts.put_json(raw) if raw is not None else None
        with self.transaction():
            self.receipt(job, outcome, artifact, usage or unavailable_usage(), duration_ms)
            if not self._fenced(job):
                return
            config = self.run(job["run"])["config"]
            count = self.db.execute(
                "SELECT attempts FROM jobs WHERE id=?", (job["id"],)
            ).fetchone()[0]
            state = (
                "execution_unknown"
                if outcome in ("execution_unknown", "cancelled")
                else ("pending" if count < config["max_attempts"] else "failed")
            )
            self.db.execute("UPDATE jobs SET state=?,expires=NULL WHERE id=?", (state, job["id"]))
            if job["case_id"] and state in ("failed", "execution_unknown"):
                self.db.execute(
                    "UPDATE cases SET state='incomplete' WHERE run=? AND id=?",
                    (job["run"], job["case_id"]),
                )

    def recover(self, run):
        # External agent jobs are quarantined; collection is safe to retry at least once.
        total = 0
        while True:
            rows = self.db.execute(
                "SELECT j.*,a.id AS attempt_id,a.invocation AS invocation_id FROM jobs j JOIN attempts a ON a.job=j.id AND a.fence=j.fence WHERE j.run=? AND j.state='running' AND j.expires<=? LIMIT 100",
                (run, time.time()),
            ).fetchall()
            if not rows:
                break
            with self.transaction():
                for row in rows:
                    job = dict(row)
                    agent = job["role"] in (*ROLES, "judge")
                    self.receipt(
                        job,
                        "execution_unknown" if agent else "interrupted",
                        None,
                        unavailable_usage("process_interrupted"),
                        None,
                    )
                    config = self.run(run)["config"]
                    state = (
                        "execution_unknown"
                        if agent
                        else ("pending" if job["attempts"] < config["max_attempts"] else "failed")
                    )
                    self.db.execute(
                        "UPDATE jobs SET state=?,expires=NULL WHERE id=?", (state, job["id"])
                    )
                    if agent:
                        self.db.execute(
                            "UPDATE cases SET state='incomplete' WHERE run=? AND id=?",
                            (run, job["case_id"]),
                        )
                    total += 1
        return total

    def retry_unknown(self, run):
        with self.transaction():
            count = self.db.execute(
                "UPDATE jobs SET state='pending' WHERE run=? AND state='execution_unknown'", (run,)
            ).rowcount
            self.event(run, "recovery", "explicit_retry_unknown", jobs=count)
        return count

    def cached(self, job):
        config = self.run(job["run"])["config"]
        key = digest(
            {"target": job["target"], "policy": config["collection"], "runtime": config["runtime"]}
        )
        row = self.db.execute(
            "SELECT bundle FROM cache WHERE key=? AND expires>?", (key, time.time())
        ).fetchone()
        if row:
            try:
                return self._verified_bundle(row[0])
            except (ValueError, OSError):
                return None
        return None

    def active(self, run, roles):
        placeholders = ",".join("?" for _ in roles)
        return self.db.execute(
            f"SELECT EXISTS(SELECT 1 FROM jobs WHERE run=? AND role IN ({placeholders}) AND state IN ('pending','running'))",
            (run, *roles),
        ).fetchone()[0]

    def finish_run(self, run):
        with self.transaction():
            current = self.run(run)
            if current["state"] in ("cancelled", "empty"):
                return current["state"]
            if self.active(run, ("collection", *ROLES, "judge", "supplemental")):
                return "running"
            self.db.execute(
                "UPDATE cases SET state='incomplete' WHERE run=? AND state NOT IN ('completed','not_assessed')",
                (run,),
            )
            incomplete = self.db.execute(
                "SELECT count(*) FROM cases WHERE run=? AND state IN ('incomplete','not_assessed')",
                (run,),
            ).fetchone()[0]
            state = "partial" if incomplete else "completed"
            if current["state"] != state:
                self.db.execute(
                    "UPDATE runs SET state=?,ended=? WHERE id=?", (state, utcnow(), run)
                )
                self.event(run, "run", state)
            return state

    def cancel(self, run):
        with self.transaction():
            self.db.execute("UPDATE runs SET state='cancelled' WHERE id=?", (run,))
            self.event(run, "run", "cancelled")

    def resume(self, run):
        with self.transaction():
            current = self.run(run)
            if current["state"] == "cancelled":
                self.db.execute(
                    "UPDATE runs SET state=? WHERE id=?",
                    ("labeling" if current["barrier"] else "collecting", run),
                )
                self.event(run, "run", "resumed")

    def verify(self, run):
        errors = []
        for table, column in (
            ("cases", "snapshot"),
            ("jobs", "result"),
            ("labels", "artifact"),
            ("reference_labels", "artifact"),
            ("rounds", "bundle"),
        ):
            for row in self.db.execute(
                f"SELECT DISTINCT {column} FROM {table} WHERE run=? AND {column} IS NOT NULL",
                (run,),
            ):
                try:
                    value = self.artifacts.get_json(row[0])
                    if "pages" in value:
                        self._verified_bundle(row[0])
                except (ValueError, OSError):
                    errors.append({"table": table, "artifact": row[0]})
        if errors:
            raise ValueError(
                f"Artifact integrity failed for {len(errors)} references; reuse blocked"
            )
        return True

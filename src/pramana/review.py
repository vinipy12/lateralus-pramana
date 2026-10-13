"""Blind review packets: the evidence a reviewer needs, without any assessment of it.

A packet is what the assessors see and nothing else. Verdicts, reason codes,
assessor and judge output, derived results, the sampling stratum, the synthetic
flag and the partition are all withheld, because each of them would tell a
reviewer what answer to give.
"""

from .artifacts import private_dir
from .contracts import blinded_company, canonical, digest
from .evidence import catalog

PACKET_VERSION = "review-packet-v1"
WITHHELD = (
    "verdict",
    "reason_codes",
    "assessor_output",
    "judge_output",
    "derived_result",
    "stratum",
    "synthetic",
    "partition",
    "source_record_reference",
)
GUIDE = """Decide, from the supplied company fields and the website evidence alone, which
verdict the evidence supports. Record a short reason naming the evidence you used.

match: the website evidence identifies the expected operating company or an evidenced
  trading brand, and at least one supplied identifier agrees with cited evidence.
  A name alone is not enough. A location agrees only at street and number level.
mismatch: positive cited evidence supports that the site represents a different,
  unrelated organization. A missing name or an unreachable page is not enough.
parked: corroborated sale or parking evidence, or template/dummy content with no
  operating company presence. A bare parking keyword is not enough.
uncertain: the evidence is insufficient, blocked, contradictory, or depends on a
  relationship the evidence does not settle.

Absence of evidence is uncertain, never mismatch. Domain equality, reachability,
redirects, generic industry similarity and a logo alone do not establish identity.
A body mention may name a customer rather than the operator. Do not look the company
up elsewhere: judge only what is in the packet, which is what the assessors saw. If you
do consult the live site or any other source, record evidence_scope as open_web instead of
packet, so that a disagreement caused by missing collection is never counted as an
assessor error.
"""


def packet(case, bundle):
    """The reviewer's view of one case: supplied fields and frozen evidence only."""
    pages, passages = catalog(bundle)
    return {
        "packet_version": PACKET_VERSION,
        "case_id": case["case_id"],
        "candidate_url": case["candidate_url"],
        "bundle_id": bundle["bundle_id"],
        "company": blinded_company(case["company"]),
        "evidence": {
            "outcome": bundle["outcome"],
            "pages": [
                {"website_page_id": handle, "final_url": page["final_url"]}
                for handle, page in pages.items()
            ],
            "passages": [
                {
                    "passage_id": handle,
                    "website_page_id": entry["website_page_id"],
                    "type": entry["type"],
                    "text": entry["excerpt"],
                }
                for handle, entry in passages.items()
            ],
        },
        "withheld": list(WITHHELD),
        "verdict_guide": GUIDE,
    }


def review_packets(store, run, reviewer):
    """Write one packet per case with usable evidence, plus a label template to fill in."""
    config = store.run(run)["config"]
    packets = []
    for row in store.db.execute(
        "SELECT c.id,c.snapshot,r.bundle FROM cases c"
        " JOIN rounds r ON r.run=c.run AND r.case_id=c.id AND r.round=c.current_round"
        " WHERE c.run=? ORDER BY c.id",
        (run,),
    ):
        bundle = store._verified_bundle(row["bundle"])
        if not catalog(bundle)[1]:
            continue
        packets.append(packet(store.artifacts.get_json(row["snapshot"]), bundle))
    packets.sort(key=lambda entry: _order(config["seed"], entry["case_id"]))
    root = private_dir(private_dir(private_dir(store.root / "runs") / run) / "review")
    (root / "packets.jsonl").write_bytes(b"".join(canonical(p) + b"\n" for p in packets))
    (root / "labels-template.jsonl").write_bytes(
        b"".join(canonical(_template(p["case_id"], reviewer)) + b"\n" for p in packets)
    )
    return root, len(packets)


def _order(seed, case_id):
    """A recorded-seed shuffle: packet order must not hint at how cases were sampled."""
    return digest({"seed": seed, "case_id": case_id})


def _template(case_id, reviewer):
    return {
        "case_id": case_id,
        "verdict": "FILL_IN: match | mismatch | parked | uncertain",
        "reviewer": reviewer,
        "origin": "independent_human",
        "blind": True,
        "evidence_scope": "packet",
        "rationale": "FILL_IN: the evidence you relied on",
        "recorded": "FILL_IN: when you reviewed this, ISO 8601",
    }

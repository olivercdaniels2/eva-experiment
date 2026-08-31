"""Assemble Eva's outgoing email from a decision record.

The model supplies restate prose and questions; every criteria sentence is
inserted verbatim from limits.json by fact ID. A numeric guard blocks any
broker-facing number that does not appear in the source enquiry.
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

NUM_RE = re.compile(r"(?:£\s?[\d,.]+\s*(?:k|m|million|thousand)?|[\d.]+\s?%|\b\d[\d,.]*\b)", re.I)


def _limits():
    return json.loads((BASE_DIR / "config" / "limits.json").read_text())


def _normalise(num: str) -> str:
    return re.sub(r"[£,%\s]|k$|m$|million$|thousand$", "", num.strip().lower())


def numeric_guard(text: str, source: str) -> list[str]:
    """Return numbers in text that never appear in the source enquiry."""
    source_nums = {_normalise(n) for n in NUM_RE.findall(source)}
    return [n for n in NUM_RE.findall(text) if _normalise(n) not in source_nums]


def _first_name(decision: dict) -> str:
    field = decision.get("extraction", {}).get("broker_name") or {}
    name = (field.get("value") or "").strip()
    return name.split()[0] if name else "there"


def build_reply(decision: dict, source_text: str) -> dict:
    """Returns {should_send, body, cc, guard_flags}."""
    limits = _limits()
    persona = limits["persona"]
    outcome = decision["outcome"]
    flags = list(decision.get("guard_flags", []))

    if outcome == "not_an_enquiry":
        return {"should_send": False, "body": "", "cc": [], "guard_flags": flags}

    # --- resolve routing to a real colleague ---
    bdms = limits["routing"]["bdms"]
    bdm_key = decision["routing"]["bdm"]
    if bdm_key not in bdms:
        bdm_key = limits["routing"]["fallback_bdm"]
    bdm = bdms[bdm_key]

    # --- numeric guard on model-drafted prose ---
    summary = decision["summary_paragraph"].strip()
    invented = numeric_guard(summary, source_text)
    if invented:
        flags.append(f"numeric_guard_summary:{invented}")
        summary = ""  # drop rather than send an invented number
    questions = []
    for q in decision["missing_info_questions"]:
        bad = numeric_guard(q, source_text)
        if bad:
            flags.append(f"numeric_guard_question:{bad}")
            continue
        questions.append(q.strip().rstrip("."))

    colleague_ask = decision["colleague_ask"].strip()
    if numeric_guard(colleague_ask, source_text):
        colleague_ask = f"{bdm['name']}, please could you pick this one up?"
        flags.append("numeric_guard_colleague_ask")

    # --- canned criteria sentences, verbatim by ID ---
    facts = [limits["policy_facts"][fid]
             for fid in decision["relevant_fact_ids"]
             if fid in limits["policy_facts"]]

    # --- assemble ---
    lines = [f"Hi {_first_name(decision)},", "", "Thank you for sending this over."]
    if summary:
        lines += ["", summary]

    cc = []
    if outcome in ("terms_request_handoff", "loop_in"):
        cc = [bdm["email"]]

    if outcome == "loop_in":
        lines += ["", f"My colleague {bdm['name']} will be best placed to assist with "
                      f"this one, so I have copied them in here.",
                  "", colleague_ask]
    else:
        if questions:
            lines += ["", "So we can take a proper look, please could you help with the following:", ""]
            lines += [f"  - {q}?" if not q.endswith("?") else f"  - {q}" for q in questions]
        if facts:
            joined = "; ".join(f[0].lower() + f[1:] for f in facts)
            lines += ["", f"By way of general criteria, {joined}."]
        if outcome == "terms_request_handoff":
            lines += ["", f"On appetite and leverage, my colleague {bdm['name']} leads on "
                          f"{bdm['leads_on']} and will come back to you directly - "
                          f"I have copied them in.",
                      "", colleague_ask]
        else:
            lines += ["", "Once I have the above I will make sure this lands with the right "
                          "person on our lending team straight away."]

    lines += ["", "We look forward to helping you get this one moving.", ""]
    if facts:
        lines += [persona["disclaimer"], ""]
    lines += [persona["signature"]]

    return {"should_send": True, "body": "\n".join(lines), "cc": cc, "guard_flags": flags}

"""Paul's brain: one structured-output call to Claude per enquiry thread.

The model extracts, flags adverse disclosures, routes, and drafts prose parts.
It cannot compose the outgoing email (reply.py owns that) and cannot write
criteria sentences (limits.json owns those, inserted verbatim by fact ID).
"""

import base64
import json
import os
from pathlib import Path

import anthropic

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("PAUL_MODEL", "claude-opus-5")

_client = None
_policy_pdf_b64 = None
_system_blocks = None


def _load_limits():
    return json.loads((BASE_DIR / "config" / "limits.json").read_text())


EXTRACTION_FIELDS = [
    "broker_name", "broker_company", "borrower_entity", "transaction_type",
    "product_type", "property_description", "location", "estimated_value",
    "purchase_price", "gdv", "loan_amount_requested", "ltv_requested",
    "term_requested", "exit_strategy", "rental_income", "cost_of_works",
    "planning_status", "timescale",
]

ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        # Array keeps the compiled grammar small (one reusable item schema);
        # decide.assess() converts it back to a dict keyed by field name.
        "extraction": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": EXTRACTION_FIELDS},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "string"},
                },
                "required": ["field", "value", "confidence", "evidence"],
                "additionalProperties": False,
            },
        },
        "adverse_disclosures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["summary", "evidence"],
                "additionalProperties": False,
            },
        },
        "routing": {
            "type": "object",
            "properties": {
                "bdm": {"type": "string", "enum": ["david", "nils", "unclear"]},
                "product_family": {"type": "string", "enum": ["SME", "AL", "unclear"]},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["bdm", "product_family", "confidence", "rationale"],
            "additionalProperties": False,
        },
        "outcome": {
            "type": "string",
            "enum": ["info_request", "terms_request_handoff", "loop_in", "not_an_enquiry"],
        },
        "relevant_fact_ids": {"type": "array", "items": {"type": "string"}},
        "missing_info_questions": {"type": "array", "items": {"type": "string"}},
        "summary_paragraph": {"type": "string"},
        "colleague_ask": {"type": "string"},
        "internal_note": {"type": "string"},
    },
    "required": [
        "extraction", "adverse_disclosures", "routing", "outcome",
        "relevant_fact_ids", "missing_info_questions", "summary_paragraph",
        "colleague_ask", "internal_note",
    ],
    "additionalProperties": False,
}


def _init():
    global _client, _policy_pdf_b64, _system_blocks
    if _client is not None:
        return
    _client = anthropic.Anthropic()
    pdf_path = Path(os.environ.get("POLICY_PDF_PATH", BASE_DIR / "credit-policy.pdf"))
    _policy_pdf_b64 = base64.standard_b64encode(pdf_path.read_bytes()).decode()

    limits = _load_limits()
    system_text = (BASE_DIR / "prompts" / "system.txt").read_text()
    # Routing config and fact IDs are stable per deploy -> part of the cached prefix.
    system_text += (
        "\n\nROUTING CONFIGURATION (authoritative):\n"
        + json.dumps(limits["routing"], indent=2)
        + "\n\nPOLICY FACT SENTENCES (for your awareness only; code inserts them verbatim):\n"
        + json.dumps(limits["policy_facts"], indent=2)
    )
    _system_blocks = [{
        "type": "text",
        "text": system_text,
        "cache_control": {"type": "ephemeral"},
    }]


def assess(thread_text: str) -> dict:
    """Run one enquiry thread through the model. Returns the decision record."""
    _init()
    response = _client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=_system_blocks,
        output_config={"format": {"type": "json_schema", "schema": ASSESSMENT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": _policy_pdf_b64,
                    },
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": "=== ENQUIRY THREAD ===\n\n" + thread_text},
            ],
        }],
    )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_read_input_tokens": response.usage.cache_read_input_tokens,
        "cache_creation_input_tokens": response.usage.cache_creation_input_tokens,
    }

    if response.stop_reason == "refusal":
        detail = ""
        if response.stop_details:
            detail = f"{response.stop_details.category}: {response.stop_details.explanation}"
        return {
            "outcome": "loop_in",
            "routing": {"bdm": "unclear", "product_family": "unclear",
                        "confidence": 0.0, "rationale": "model refusal"},
            "extraction": {}, "adverse_disclosures": [],
            "relevant_fact_ids": [], "missing_info_questions": [],
            "summary_paragraph": "", "colleague_ask": "",
            "internal_note": f"Model refused to assess ({detail}). Human review required.",
            "guard_flags": ["model_refusal"],
            "model": response.model, "usage": usage,
        }

    text = next(b.text for b in response.content if b.type == "text")
    decision = json.loads(text)
    decision["extraction"] = {
        item["field"]: {"value": item["value"], "confidence": item["confidence"],
                        "evidence": item["evidence"]}
        for item in decision["extraction"]
    }
    decision["guard_flags"] = []
    decision["model"] = response.model
    decision["usage"] = usage

    # Code-enforced overrides - never left to the model:
    # 1. Any adverse disclosure means a BDM sees it now (upgrade info_request).
    if decision["adverse_disclosures"] and decision["outcome"] == "info_request":
        decision["outcome"] = "terms_request_handoff"
        decision["guard_flags"].append("adverse_forced_handoff")
    # 2. Routing confidence below floor -> loop in the fallback desk.
    limits = _load_limits()
    if (decision["outcome"] != "not_an_enquiry"
            and decision["routing"]["confidence"] < limits["routing"]["min_routing_confidence"]):
        decision["routing"]["bdm"] = "unclear"
        if decision["outcome"] == "info_request":
            decision["outcome"] = "loop_in"
            decision["guard_flags"].append("low_routing_confidence")

    return decision

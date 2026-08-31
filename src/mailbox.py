"""Mailbox adapter. The engine only ever talks to this interface.

MimicMailbox = Supabase-backed fake inbox for the Experiment sandbox.
When the real domain lands on a provider, add GraphMailbox / GmailMailbox
with the same four methods and switch via the MAILBOX env var.
"""

import json
import os
from dataclasses import dataclass, field

from supabase import create_client


@dataclass
class Message:
    id: str
    thread_id: str
    direction: str
    from_name: str
    from_email: str
    subject: str
    body: str
    attachments_text: str = ""
    cc_emails: list = field(default_factory=list)
    created_at: str = ""


def _to_message(row: dict) -> Message:
    return Message(
        id=row["id"], thread_id=row["thread_id"], direction=row["direction"],
        from_name=row.get("from_name") or "", from_email=row.get("from_email") or "",
        subject=row.get("subject") or "", body=row.get("body") or "",
        attachments_text=row.get("attachments_text") or "",
        cc_emails=row.get("cc_emails") or [], created_at=row.get("created_at") or "",
    )


class MimicMailbox:
    def __init__(self):
        self.sb = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"]
        )

    def fetch_unprocessed(self) -> list[Message]:
        rows = (self.sb.table("mimic_messages").select("*")
                .eq("direction", "inbound").eq("status", "unread")
                .order("created_at").execute().data)
        return [_to_message(r) for r in rows]

    def fetch_thread(self, thread_id: str) -> list[Message]:
        rows = (self.sb.table("mimic_messages").select("*")
                .eq("thread_id", thread_id).order("created_at").execute().data)
        return [_to_message(r) for r in rows]

    def mark(self, message_id: str, status: str):
        self.sb.table("mimic_messages").update({"status": status}).eq("id", message_id).execute()

    def send_reply(self, thread_id: str, subject: str, body: str,
                   from_name: str, from_email: str, to_email: str, cc: list) -> str:
        row = (self.sb.table("mimic_messages").insert({
            "thread_id": thread_id, "direction": "outbound",
            "from_name": from_name, "from_email": from_email,
            "to_email": to_email, "cc_emails": cc,
            "subject": subject if subject.lower().startswith("re:") else f"Re: {subject}",
            "body": body, "status": "sent",
        }).execute().data)[0]
        return row["id"]

    def log_decision(self, message_id: str, thread_id: str, decision: dict,
                     reply_body: str, guard_flags: list):
        self.sb.table("enquiry_decisions").insert({
            "message_id": message_id, "thread_id": thread_id,
            "extraction": decision.get("extraction"),
            "decision": {k: v for k, v in decision.items()
                         if k not in ("extraction", "usage", "model", "guard_flags")},
            "reply_body": reply_body, "guard_flags": guard_flags,
            "model": decision.get("model"), "usage": decision.get("usage"),
        }).execute()


def get_mailbox():
    kind = os.environ.get("MAILBOX", "mimic")
    if kind == "mimic":
        return MimicMailbox()
    raise ValueError(f"Unknown MAILBOX '{kind}' - only 'mimic' is implemented so far")

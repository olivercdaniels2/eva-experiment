"""Eva's worker loop: poll mailbox -> assess -> reply instantly -> log.

Instant replies by design (Experiment sandbox). When this graduates to a real
mailbox, add the business-hours-clamped random delay here, between assess()
and send_reply().
"""

import json
import os
import time
import traceback
from pathlib import Path

from . import decide, reply
from .mailbox import get_mailbox

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def thread_to_text(messages) -> str:
    parts = []
    for m in messages:
        part = (f"From: {m.from_name} <{m.from_email}>\n"
                f"Subject: {m.subject}\n\n{m.body}")
        if m.attachments_text:
            part += f"\n\n[ATTACHMENT CONTENT]\n{m.attachments_text}"
        parts.append(part)
    return "\n\n--- earlier/next message in thread ---\n\n".join(parts)


def process(mailbox, msg):
    print(f"[eva] processing {msg.id} from {msg.from_email}: {msg.subject!r}")
    mailbox.mark(msg.id, "processing")
    thread = mailbox.fetch_thread(msg.thread_id)
    source_text = thread_to_text(thread)

    decision = decide.assess(source_text)
    out = reply.build_reply(decision, source_text)

    persona = json.loads((BASE_DIR / "config" / "limits.json").read_text())["persona"]
    if out["should_send"]:
        mailbox.send_reply(
            thread_id=msg.thread_id, subject=msg.subject, body=out["body"],
            from_name=persona["name"], from_email=persona["email"],
            to_email=msg.from_email, cc=out["cc"],
        )
        mailbox.mark(msg.id, "replied")
    else:
        mailbox.mark(msg.id, "ignored")

    mailbox.log_decision(msg.id, msg.thread_id, decision, out["body"], out["guard_flags"])
    print(f"[eva] done {msg.id}: outcome={decision['outcome']} "
          f"route={decision['routing']['bdm']} flags={out['guard_flags']} "
          f"cache_read={decision['usage']['cache_read_input_tokens']}")


def run():
    _load_env_file()
    mailbox = get_mailbox()
    poll = int(os.environ.get("POLL_SECONDS", "10"))
    print(f"[eva] worker started, polling every {poll}s")
    while True:
        try:
            for msg in mailbox.fetch_unprocessed():
                try:
                    process(mailbox, msg)
                except Exception:
                    traceback.print_exc()
                    mailbox.mark(msg.id, "error")
        except Exception:
            traceback.print_exc()
        time.sleep(poll)


if __name__ == "__main__":
    run()

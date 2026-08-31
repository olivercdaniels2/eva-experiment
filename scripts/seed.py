"""Drop a sample enquiry into the mimic mailbox as an unread inbound message.

Usage:  python -m scripts.seed samples/sunny.txt
The worker picks it up on its next poll; watch it in eva-console.html.
"""

import os
import re
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from supabase import create_client  # noqa: E402


def load_env():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def parse_sample(text: str) -> dict:
    """Pull From:/Subject: headers off a sample file; rest is the body."""
    name, email, subject = "Test Broker", "broker@example.co.uk", "New enquiry"
    lines = text.splitlines()
    body_start = 0
    for i, line in enumerate(lines):
        if m := re.match(r"^From:\s*(.*?)\s*<(.+?)>\s*$", line):
            name, email = m.group(1), m.group(2)
            body_start = i + 1
        elif m := re.match(r"^Subject:\s*(.+)$", line):
            subject = m.group(1).strip()
            body_start = i + 1
        elif line.strip() == "" and body_start:
            body_start = i + 1
            break
    return {"from_name": name, "from_email": email, "subject": subject,
            "body": "\n".join(lines[body_start:]).strip()}


def main():
    load_env()
    sample = BASE_DIR / (sys.argv[1] if len(sys.argv) > 1 else "samples/sunny.txt")
    row = parse_sample(sample.read_text())
    row |= {"thread_id": str(uuid.uuid4()), "direction": "inbound",
            "to_email": "eva@alba.loans", "status": "unread"}

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    data = sb.table("mimic_messages").insert(row).execute().data[0]
    print(f"seeded message {data['id']}")
    print(f"  thread  {data['thread_id']}")
    print(f"  from    {row['from_name']} <{row['from_email']}>")
    print(f"  subject {row['subject']}")


if __name__ == "__main__":
    main()

# Eva — AI Enquiry Consultant (Experiment sandbox)

An isolated experiment: an LLM-based enquiry triage agent ("Eva Fitzgerald") that reads
inbound broker enquiries, extracts the deal with per-field confidence + verbatim evidence,
checks it against the credit policy, and replies — asking for missing material facts,
quoting only whitelisted criteria sentences, and looping in the right BDM
(David = SME, Nils = everything else). Instant replies, mimic mailbox, zero contact
with production systems.

## Architecture

- **Mimic mailbox**: `mimic_messages` table in the *Experiment* Supabase project
  (`jiximtizoodrpvfjdxaq`) plays the inbox. `eva-console.html` is the fake mail client —
  compose enquiries as a broker, watch Eva reply in-thread, click "Why did Eva do this?"
  for the extraction ledger and audit trail.
- **Worker** (`src/main.py`): polls for unread inbound mail, runs `decide.assess()`
  (one structured-output call to Claude Opus 5 with the credit policy PDF attached and
  prompt-cached), assembles the reply in code (`reply.py`), sends, logs to
  `enquiry_decisions`.
- **Guardrails in code, not prompt**: criteria sentences are inserted verbatim from
  `config/limits.json` by fact ID; a numeric guard strips any broker-facing number not
  present in the source enquiry; adverse disclosures force a BDM CC; low routing
  confidence forces loop-in. Server-side refusal fallbacks are enabled
  (`fallbacks: "default"`) so a safety decline degrades gracefully.

## Setup (once)

1. **Database**: run `migration.sql` in the Experiment project's SQL editor
   (or via the Supabase MCP once authenticated).
2. **Keys**: fill `SUPABASE_SERVICE_KEY` in `.env` (Project Settings → API keys →
   service_role). The console asks once for the anon key and stores it in localStorage.
3. **Run locally**:
   ```bash
   cd paul-agent
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m scripts.run_sample samples/sunny.txt   # brain only, no DB
   .venv/bin/python -m src.main                               # full worker loop
   ```
4. **Console**: open `eva-console.html` in a browser (any static server or file://).

## Deploy to Render

Blueprint in `render.yaml` (worker service, rootDir `paul-agent`). Or create a
Background Worker manually: build `pip install -r requirements.txt`, start
`python -m src.main`, env vars `ANTHROPIC_API_KEY`, `SUPABASE_URL`,
`SUPABASE_SERVICE_KEY`, `MAILBOX=mimic`, `POLL_SECONDS=10`.

## Things marked EDIT ME

- `config/limits.json` → `thresholds` and `policy_facts`: verify every number against
  `credit-policy.pdf` before showing anyone. Facts are the ONLY criteria Eva can state.
- Persona (name/signature/disclaimer) also lives in `limits.json`.

## Graduating from the sandbox

- Real mailbox: implement `GraphMailbox`/`GmailMailbox` in `src/mailbox.py` (same four
  methods), set `MAILBOX` env var. The domain change is config, not code.
- Human-feel delay: add the business-hours-clamped random delay in `src/main.py`
  (marked in the docstring) — deliberately absent in the sandbox.
- Rotate the Anthropic API key used during the experiment (it was shared in chat).

-- ============================================================
-- Eva (Experiment) – Supabase Migration
-- Run this ENTIRE script in the NEW Experiment project SQL Editor:
-- https://supabase.com/dashboard/project/jiximtizoodrpvfjdxaq/sql/new
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. MIMIC MESSAGES (fake mailbox: inbound = broker, outbound = Eva)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.mimic_messages (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    thread_id UUID NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    from_name TEXT,
    from_email TEXT,
    to_email TEXT,
    cc_emails TEXT[] DEFAULT '{}',
    subject TEXT,
    body TEXT NOT NULL,
    attachments_text TEXT,            -- pasted attachment content (mimic only)
    status TEXT NOT NULL DEFAULT 'unread',  -- unread|processing|replied|ignored|error|sent
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_mimic_thread ON public.mimic_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_mimic_unread ON public.mimic_messages(direction, status);

-- ============================================================
-- 2. ENQUIRY DECISIONS (audit trail: one row per Eva assessment)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.enquiry_decisions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    message_id UUID REFERENCES public.mimic_messages(id),
    thread_id UUID,
    extraction JSONB,
    decision JSONB,
    reply_body TEXT,
    guard_flags TEXT[] DEFAULT '{}',
    model TEXT,
    usage JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decisions_message ON public.enquiry_decisions(message_id);

-- ============================================================
-- 3. RLS (sandbox-permissive: anon can read/write so the console works)
-- ============================================================
ALTER TABLE public.mimic_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enquiry_decisions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "anon all mimic" ON public.mimic_messages;
CREATE POLICY "anon all mimic" ON public.mimic_messages
    FOR ALL USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "anon all decisions" ON public.enquiry_decisions;
CREATE POLICY "anon all decisions" ON public.enquiry_decisions
    FOR ALL USING (true) WITH CHECK (true);

-- ============================================================
-- 4. Realtime for the console (ignore error if already added)
-- ============================================================
DO $$ BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.mimic_messages;
EXCEPTION WHEN OTHERS THEN NULL; END $$;

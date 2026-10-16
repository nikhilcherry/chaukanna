-- =============================================================================
-- Chaukanna incident responder: Supabase schema + demo seeds
--
-- Paste the whole file into Supabase -> SQL Editor -> Run. It is idempotent:
-- running it again changes nothing and never overwrites rows you edited
-- (for example the real Telegram chat id you put on the demo contact).
--
-- Tables (as specified):
--   scam_numbers       shared blocklist, one row per scam phone number
--   trusted_contacts   who to alert for each victim (Telegram chat id)
--   incident_evidence  one row per scam call: transcript, 1930 draft, status
--
-- Columns the spec asked for are listed first in each table. Columns after the
-- "added for the n8n workflow" comment are extra fields the workflow writes.
-- Spec columns are never renamed.
--
-- Security: RLS is ON for every table with NO policies, so the anon and
-- authenticated keys can read and write nothing. n8n connects with the
-- service_role key, which bypasses RLS. The Flutter app never talks to
-- Supabase directly; it goes through n8n webhooks. If you add a dashboard
-- later, add narrow SELECT policies for it instead of turning RLS off.
-- =============================================================================

create extension if not exists pgcrypto;   -- gen_random_uuid() on older Postgres

-- ---------------------------------------------------------------------------
-- enum: complaint_status
-- ---------------------------------------------------------------------------
do $$
begin
  create type public.complaint_status as enum ('draft_pending_human', 'submitted');
exception
  when duplicate_object then null;          -- already exists: keep it
end
$$;

-- ---------------------------------------------------------------------------
-- scam_numbers: the shared blocklist (feedback loop: every incident adds to it)
-- ---------------------------------------------------------------------------
create table if not exists public.scam_numbers (
  phone_number  text primary key,            -- E.164, e.g. +919876543210 (n8n normalizes)
  scam_type     text        not null default 'other',
                                             -- digital_arrest | kyc_update | bank_impersonation
                                             -- | prize_lottery | other
  report_count  integer     not null default 1,
  first_seen    timestamptz not null default now(),
  last_seen     timestamptz not null default now(),
  risk_level    text        not null default 'high',
  -- added for the n8n workflow
  last_call_id  text,                        -- report_count goes up at most once per call
  constraint scam_numbers_phone_e164  check (phone_number ~ '^\+[0-9]{8,15}$'),
  constraint scam_numbers_count_pos   check (report_count >= 0),
  constraint scam_numbers_risk_level  check (risk_level in ('low', 'medium', 'high', 'critical'))
);

-- ---------------------------------------------------------------------------
-- trusted_contacts: one row per (victim, contact). victim_name and
-- preferred_language repeat on each row so one lookup gives n8n everything.
--   preferred_language = the VICTIM's language, used for the local-language
--   copy of the 1930 complaint when the call itself was in English.
--   telegram_chat_id   = the contact's chat with the Chaukanna bot (text,
--   because group chat ids are large negative numbers like -1001234567890).
-- ---------------------------------------------------------------------------
create table if not exists public.trusted_contacts (
  victim_id           text not null,
  victim_name         text not null,
  contact_name        text not null,
  telegram_chat_id    text,
  phone_number        text,                  -- the contact's phone
  preferred_language  text not null default 'hi',   -- hi | kn | en | ta | te | ...
  -- added for the n8n workflow
  id                  bigint generated always as identity,
  created_at          timestamptz not null default now(),
  constraint trusted_contacts_pkey primary key (id),
  constraint trusted_contacts_victim_contact_key unique (victim_id, contact_name)
);

-- ---------------------------------------------------------------------------
-- incident_evidence: one row per scam call (call_id is unique = n8n dedupe)
-- ---------------------------------------------------------------------------
create table if not exists public.incident_evidence (
  id                     uuid primary key default gen_random_uuid(),
  call_id                text        not null,
  victim_id              text        not null,
  caller_number          text,
  scam_type              text,
  max_pressure           smallint    not null default 0,
  transcript_json        jsonb       not null default '[]'::jsonb,
  complaint_draft_text   text,                       -- English 1930 complaint
  complaint_status       public.complaint_status not null default 'draft_pending_human',
  created_at             timestamptz not null default now(),
  -- added for the n8n workflow
  complaint_draft_local  text,                       -- same complaint in the victim's language
  language               text,                       -- language of complaint_draft_local
  family_alert_text      text,                       -- the AI's 3-bullet family alert
  asks_otp_or_pin        boolean     not null default false,
  demands_secrecy        boolean     not null default false,
  known_scammer          boolean     not null default false,
  approve_url            text,                       -- n8n Wait-node resume URL (signed)
  last_event             text,                       -- incident | escalation | call_ended
  family_response        text,                       -- ack | false_alarm (Telegram button)
  family_response_at     timestamptz,
  submitted_at           timestamptz,
  submitted_by           text,
  updated_at             timestamptz not null default now(),
  constraint incident_evidence_call_id_key unique (call_id),
  constraint incident_evidence_pressure check (max_pressure between 0 and 3)
);

-- ---------------------------------------------------------------------------
-- Integrity rules enforced by the database, not just by n8n
--   * max_pressure never goes down within a call (matches the classifier rule)
--   * a submitted complaint can't go back to draft
--   * updated_at is maintained automatically
-- ---------------------------------------------------------------------------
create or replace function public.incident_evidence_guard()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  new.updated_at := now();
  if tg_op = 'UPDATE' then
    new.max_pressure := greatest(coalesce(old.max_pressure, 0), coalesce(new.max_pressure, 0));
    new.asks_otp_or_pin := old.asks_otp_or_pin or new.asks_otp_or_pin;
    new.demands_secrecy := old.demands_secrecy or new.demands_secrecy;
    if old.complaint_status = 'submitted' and new.complaint_status <> 'submitted' then
      new.complaint_status := 'submitted';
    end if;
  end if;
  return new;
end
$$;

drop trigger if exists incident_evidence_guard on public.incident_evidence;
create trigger incident_evidence_guard
  before insert or update on public.incident_evidence
  for each row execute function public.incident_evidence_guard();

-- ---------------------------------------------------------------------------
-- Indexes (primary keys and unique constraints already index phone_number,
-- id, call_id and (victim_id, contact_name))
-- ---------------------------------------------------------------------------
create index if not exists scam_numbers_last_seen_idx
  on public.scam_numbers (last_seen desc);
create index if not exists incident_evidence_victim_created_idx
  on public.incident_evidence (victim_id, created_at desc);
create index if not exists incident_evidence_caller_idx
  on public.incident_evidence (caller_number, created_at desc);
create index if not exists incident_evidence_pending_idx
  on public.incident_evidence (created_at desc)
  where complaint_status = 'draft_pending_human';

-- ---------------------------------------------------------------------------
-- Row Level Security: on, no policies (service_role only). See header.
-- ---------------------------------------------------------------------------
alter table public.scam_numbers      enable row level security;
alter table public.trusted_contacts  enable row level security;
alter table public.incident_evidence enable row level security;

-- Supabase normally grants table access to service_role through default
-- privileges. Grant it explicitly too, so the n8n credential works even on a
-- project where those defaults were changed. Skipped on plain Postgres.
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant usage on schema public to service_role;
    grant select, insert, update, delete
      on public.scam_numbers, public.trusted_contacts, public.incident_evidence
      to service_role;
  end if;
end
$$;

-- ---------------------------------------------------------------------------
-- Seeds (insert-only: re-running never overwrites your edits)
-- ---------------------------------------------------------------------------

-- 3 sample scam numbers.
--   +919988776655  the app simulator's "Known Scammer Auto-Block" caller
--   +923001234567  digital-arrest caller from a scam-compound country code (+92)
--   +85512345678   lottery / task scam from Cambodia (+855)
-- +919876543210 (the scammer dialer's default) is deliberately NOT seeded: the
-- first high-risk call adds it, so a redial from it shows "known scammer".
insert into public.scam_numbers
  (phone_number, scam_type, report_count, first_seen, last_seen, risk_level)
values
  ('+919988776655', 'kyc_update',     7,  now() - interval '21 days', now() - interval '2 days',  'high'),
  ('+923001234567', 'digital_arrest', 23, now() - interval '60 days', now() - interval '6 hours', 'critical'),
  ('+85512345678',  'prize_lottery',  4,  now() - interval '9 days',  now() - interval '1 day',   'medium')
on conflict (phone_number) do nothing;

-- Demo victim profile. Put your real Telegram chat id here after seeding:
--   update public.trusted_contacts
--      set telegram_chat_id = '<your chat id>'
--    where victim_id = 'demo-victim-1' and contact_name = 'Ravi (son)';
insert into public.trusted_contacts
  (victim_id, victim_name, contact_name, telegram_chat_id, phone_number, preferred_language)
values
  ('demo-victim-1', 'Kamala Devi', 'Ravi (son)', 'REPLACE_WITH_TELEGRAM_CHAT_ID', '+919845012345', 'hi')
on conflict (victim_id, contact_name) do nothing;

-- ---------------------------------------------------------------------------
-- Quick checks
--   select * from public.scam_numbers order by last_seen desc;
--   select victim_id, contact_name, telegram_chat_id from public.trusted_contacts;
--   select id, call_id, max_pressure, complaint_status, created_at
--     from public.incident_evidence order by created_at desc limit 10;
-- Reset demo data between rehearsals:
--   delete from public.incident_evidence;
--   delete from public.scam_numbers where phone_number = '+919876543210';
-- ---------------------------------------------------------------------------

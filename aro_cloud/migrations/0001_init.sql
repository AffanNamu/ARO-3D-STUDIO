-- ARO 3D AI STUDIO: production schema, migration 0001 (Supabase / PostgreSQL 15+).
--
-- Applied by `python -m aro_cloud.migrate`. Exercised in CI against a real PostgreSQL 16 (tests/cloud), with the minimum of Supabase's
-- `auth` schema stubbed (aro_cloud/dev/supabase_stub.sql, dev/CI only). NOT yet applied to the owner's Supabase project.
-- Principles (docs/cto/04-architecture.md):
--   * PostgreSQL is the source of truth for jobs, credits and assets. Redis (if added) only coordinates.
--   * Every user-owned row carries owner_id and is protected by Row Level Security.
--   * Credits move only through SECURITY DEFINER functions; clients never write the ledger or balances.
--   * Money-like quantities are integers (credits) or numeric (USD estimates); never floats.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------------------------------------------- types
create type job_state as enum (
  'created', 'validating', 'queued', 'initializing', 'generating', 'processing',
  'validating_output', 'uploading', 'completed', 'failed', 'cancelled'
);
create type job_kind as enum (
  'text_to_3d', 'image_to_3d', 'multi_image_to_3d', 'retexture', 'remesh', 'rig', 'animate', 'export'
);
create type ledger_kind as enum ('grant', 'purchase', 'reserve', 'release', 'capture', 'refund', 'adjustment');
create type record_status as enum ('active', 'archived', 'deleted');
create type licence_status as enum ('verified', 'claimed', 'evaluation_only', 'blocked');

-- ------------------------------------------------------------------------------------------------------------- accounts
create table profiles (
  user_id      uuid primary key references auth.users (id) on delete cascade,
  display_name text check (char_length(display_name) <= 80),
  created_at   timestamptz not null default now()
);

create table credit_accounts (
  user_id    uuid primary key references auth.users (id) on delete cascade,
  balance    integer not null default 0 check (balance >= 0),   -- spendable credits (reserved credits are already deducted)
  reserved   integer not null default 0 check (reserved >= 0),  -- informational: credits currently held by running jobs
  updated_at timestamptz not null default now()
);

-- ------------------------------------------------------------------------------------------------ projects, assets, files
create table projects (
  project_id uuid primary key default gen_random_uuid(),
  owner_id   uuid not null references auth.users (id) on delete cascade,
  parent_id  uuid references projects (project_id) on delete set null,  -- folders
  name       text not null check (char_length(name) between 1 and 120),
  status     record_status not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index projects_owner_idx on projects (owner_id, status);

create table assets (
  asset_id           uuid primary key default gen_random_uuid(),
  owner_id           uuid not null references auth.users (id) on delete cascade,
  project_id         uuid references projects (project_id) on delete set null,
  name               text not null check (char_length(name) between 1 and 120),
  category           text not null default 'other',
  status             record_status not null default 'active',
  current_version_id uuid,                                  -- set after the first version exists
  metadata           jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  deleted_at         timestamptz                            -- soft delete; a retention job purges after the policy window
);
create index assets_owner_idx on assets (owner_id, status, updated_at desc);
create index assets_search_idx on assets using gin (to_tsvector('simple', name));

create table asset_versions (
  version_id        uuid primary key default gen_random_uuid(),
  asset_id          uuid not null references assets (asset_id) on delete cascade,
  owner_id          uuid not null references auth.users (id) on delete cascade,  -- denormalised so RLS needs no join
  version_no        integer not null check (version_no >= 1),
  label             text,
  parent_version_id uuid references asset_versions (version_id) on delete set null,
  produced_by_job   uuid,                                   -- generation_jobs.job_id (added below, avoids a cycle)
  geometry_stats    jsonb not null default '{}'::jsonb,     -- triangles, vertices, bounds, components, has_uv ...
  validation        jsonb not null default '{}'::jsonb,     -- rule results, status
  provenance        jsonb not null default '{}'::jsonb,     -- model id/version, settings, input sha256, whether AI or conventional
  created_at        timestamptz not null default now(),
  unique (asset_id, version_no)
);
alter table assets add constraint assets_current_version_fk
  foreign key (current_version_id) references asset_versions (version_id) on delete set null;

create table files (
  file_id      uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references auth.users (id) on delete cascade,
  version_id   uuid references asset_versions (version_id) on delete cascade,
  role         text not null check (role in ('source_image', 'raw_mesh', 'glb', 'texture', 'preview', 'thumbnail', 'export')),
  r2_key       text not null unique,                        -- users/<owner_id>/assets/<asset_id>/v<n>/<role>/<sha256>.<ext>
  content_type text not null,
  bytes        bigint not null check (bytes >= 0),
  sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  created_at   timestamptz not null default now()
);
create index files_version_idx on files (version_id, role);

-- --------------------------------------------------------------------------------------------------- models and providers
create table model_registry (
  model_id            text primary key,                     -- e.g. 'trellis2-4b'
  task                text not null,                        -- image_to_3d, text_to_image, retexture, rig ...
  version             text not null,
  provider            text not null,                        -- 'runpod', 'local', ...
  code_licence_spdx   text,
  weights_licence     text,
  weights_licence_url text,
  licence_status      licence_status not null default 'claimed',
  verified_by         text,                                 -- the person who read the weights licence
  verified_at         timestamptz,
  enabled             boolean not null default false,
  check (not enabled or licence_status = 'verified')        -- an unverified or restricted model can never be enabled
);

-- ---------------------------------------------------------------------------------------------------------------- uploads
-- Input images. The API validates content (magic bytes, decode, pixel limits) before the object is stored; clients never write to storage.
create table uploads (
  upload_id    uuid primary key default gen_random_uuid(),
  owner_id     uuid not null references auth.users (id) on delete cascade,
  r2_key       text not null unique,
  content_type text not null check (content_type in ('image/png', 'image/jpeg', 'image/webp')),
  bytes        integer not null check (bytes > 0),
  sha256       text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  width        integer not null check (width > 0),
  height       integer not null check (height > 0),
  has_alpha    boolean not null,
  created_at   timestamptz not null default now()
);
create index uploads_owner_idx on uploads (owner_id, created_at desc);

-- Models known to the platform. NOTHING is enabled until a person records the licence attestation (python -m aro_cloud.admin verify-model).
insert into model_registry (model_id, task, version, provider, code_licence_spdx, weights_licence, weights_licence_url, licence_status, enabled) values
  ('triposg', 'image_to_3d', 'VAST-AI/TripoSG', 'runpod', 'MIT', 'MIT (Hugging Face card, read 2026-11-08)', 'https://huggingface.co/VAST-AI/TripoSG', 'claimed', false),
  ('trellis2', 'image_to_3d', 'microsoft/TRELLIS.2-4B', 'runpod', 'MIT', 'MIT; but nvdiffrast (non-commercial) is in the export path', 'https://huggingface.co/microsoft/TRELLIS.2-4B', 'evaluation_only', false),
  ('hunyuan3d', 'image_to_3d', 'tencent/Hunyuan3D-2', 'runpod', 'Tencent Community Licence', 'Tencent Community Licence (excludes EU, UK, South Korea)', 'https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/LICENSE', 'evaluation_only', false)
on conflict (model_id) do nothing;

-- ------------------------------------------------------------------------------------------------------------------ jobs
create table generation_jobs (
  job_id              uuid primary key default gen_random_uuid(),
  owner_id            uuid not null references auth.users (id) on delete cascade,
  project_id          uuid references projects (project_id) on delete set null,
  upload_id           uuid references uploads (upload_id) on delete set null,
  name                text not null default 'Untitled' check (char_length(name) between 1 and 120),
  kind                job_kind not null,
  state               job_state not null default 'created',
  progress            numeric(4, 3) not null default 0 check (progress between 0 and 1),
  status_message      text,
  idempotency_key     text not null check (char_length(idempotency_key) between 8 and 128),
  request             jsonb not null,                       -- validated request, including settings and input file ids
  request_sha256      text not null,
  model_id            text references model_registry (model_id),
  provider            text,
  provider_run_id     text,                                 -- e.g. the RunPod job id; the key for reconciliation
  dispatch_started_at timestamptz,                          -- set BEFORE the provider is called; a run id may or may not exist after a crash
  attempt             integer not null default 0 check (attempt >= 0),
  max_attempts        integer not null default 1 check (max_attempts between 1 and 3),
  credits_reserved    integer not null default 0 check (credits_reserved >= 0),
  credits_captured    integer not null default 0 check (credits_captured >= 0),
  cancel_requested    boolean not null default false,
  error_code          text,
  error_message       text,
  result_version_id   uuid references asset_versions (version_id) on delete set null,
  cost_usd_estimated  numeric(10, 5),
  cost_usd_actual     numeric(10, 5),
  deadline_at         timestamptz not null,                 -- hard stop: past this the job is reconciled, never blindly retried
  started_at          timestamptz,
  finished_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (owner_id, idempotency_key),
  check (credits_captured <= credits_reserved)
);
create index jobs_active_idx on generation_jobs (state, deadline_at)
  where state not in ('completed', 'failed', 'cancelled');
create index jobs_owner_idx on generation_jobs (owner_id, created_at desc);
alter table asset_versions add constraint versions_job_fk
  foreign key (produced_by_job) references generation_jobs (job_id) on delete set null;

create table job_events (
  event_id   bigint generated always as identity primary key,
  job_id     uuid not null references generation_jobs (job_id) on delete cascade,
  at         timestamptz not null default now(),
  from_state job_state,
  to_state   job_state not null,
  detail     jsonb not null default '{}'::jsonb              -- provider status, timings, error text (never secrets)
);
create index job_events_job_idx on job_events (job_id, at);

-- ----------------------------------------------------------------------------------------------- credits (append-only)
create table credit_ledger (
  entry_id      bigint generated always as identity primary key,
  user_id       uuid not null references auth.users (id) on delete cascade,
  kind          ledger_kind not null,
  amount        integer not null,                           -- signed; reserve is negative, release/refund/grant are positive, capture is 0
  balance_after integer not null check (balance_after >= 0),
  job_id        uuid references generation_jobs (job_id) on delete set null,
  note          text,
  at            timestamptz not null default now()
);
create index ledger_user_idx on credit_ledger (user_id, at desc);
create unique index ledger_one_reserve_per_job on credit_ledger (job_id) where kind = 'reserve';
create unique index ledger_one_capture_per_job on credit_ledger (job_id) where kind = 'capture';
create unique index ledger_one_release_per_job on credit_ledger (job_id) where kind = 'release';

create table usage_records (
  usage_id bigint generated always as identity primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  job_id   uuid references generation_jobs (job_id) on delete set null,
  metric   text not null,                                   -- gpu_seconds, storage_bytes, egress_bytes ...
  quantity numeric not null check (quantity >= 0),
  unit     text not null,
  cost_usd numeric(10, 5),
  at       timestamptz not null default now()
);

create table audit_log (
  audit_id  bigint generated always as identity primary key,
  actor_id  uuid,
  action    text not null,
  target    text,
  detail    jsonb not null default '{}'::jsonb,
  at        timestamptz not null default now()
);

-- --------------------------------------------------------------------------------------------------- credit functions
-- Reserve credits for a job: atomic, refuses when the balance is too small, safe to call twice for the same job.
create or replace function reserve_credits(p_user uuid, p_job uuid, p_amount integer)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  new_balance integer;
begin
  if p_amount < 0 then
    raise exception 'amount must be non-negative';
  end if;
  if exists (select 1 from credit_ledger where job_id = p_job and kind = 'reserve') then
    return (select balance from credit_accounts where user_id = p_user);  -- idempotent
  end if;
  if exists (select 1 from credit_ledger where job_id = p_job and kind in ('capture', 'release')) then
    raise exception 'job already settled';  -- credits can never be held for a job whose accounting is closed
  end if;
  if not exists (select 1 from generation_jobs where job_id = p_job and owner_id = p_user) then
    raise exception 'unknown job';
  end if;
  update credit_accounts
     set balance = balance - p_amount, reserved = reserved + p_amount, updated_at = now()
   where user_id = p_user and balance >= p_amount
   returning balance into new_balance;
  if not found then
    raise exception 'insufficient credits' using errcode = 'P0001';
  end if;
  insert into credit_ledger (user_id, kind, amount, balance_after, job_id)
  values (p_user, 'reserve', -p_amount, new_balance, p_job);
  update generation_jobs set credits_reserved = p_amount, updated_at = now() where job_id = p_job;
  return new_balance;
end;
$$;

-- Capture: the job succeeded. The reserve is kept; a zero-amount entry records the decision.
create or replace function capture_credits(p_user uuid, p_job uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  held integer;
begin
  select credits_reserved into held from generation_jobs where job_id = p_job and owner_id = p_user for update;
  if not found then
    raise exception 'unknown job';
  end if;
  if exists (select 1 from credit_ledger where job_id = p_job and kind in ('capture', 'release')) then
    return;  -- already settled
  end if;
  if not exists (select 1 from credit_ledger where job_id = p_job and kind = 'reserve') then
    raise exception 'no reservation for this job';  -- capturing credits that were never held would be a bug, not a no-op
  end if;
  update credit_accounts set reserved = greatest(reserved - held, 0), updated_at = now() where user_id = p_user;
  insert into credit_ledger (user_id, kind, amount, balance_after, job_id)
  select p_user, 'capture', 0, balance, p_job from credit_accounts where user_id = p_user;
  update generation_jobs set credits_captured = held, updated_at = now() where job_id = p_job;
end;
$$;

-- Release: the job failed or was cancelled. Give the reserve back (a failed generation is not charged).
create or replace function release_credits(p_user uuid, p_job uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  held integer;
  new_balance integer;
begin
  select credits_reserved into held from generation_jobs where job_id = p_job and owner_id = p_user for update;
  if not found then
    raise exception 'unknown job';
  end if;
  if exists (select 1 from credit_ledger where job_id = p_job and kind in ('capture', 'release')) then
    return;  -- already settled
  end if;
  if not exists (select 1 from credit_ledger where job_id = p_job and kind = 'reserve') then
    return;  -- nothing was ever held, so there is nothing to give back (and nothing is written)
  end if;
  update credit_accounts
     set balance = balance + held, reserved = greatest(reserved - held, 0), updated_at = now()
   where user_id = p_user
   returning balance into new_balance;
  insert into credit_ledger (user_id, kind, amount, balance_after, job_id)
  values (p_user, 'release', held, new_balance, p_job);
end;
$$;

-- Make sure a user has a profile and a credit account (idempotent; called by the API on first authenticated request).
create or replace function ensure_user(p_user uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into profiles (user_id) values (p_user) on conflict (user_id) do nothing;
  insert into credit_accounts (user_id) values (p_user) on conflict (user_id) do nothing;
end;
$$;

-- Grant credits (owner decision, via python -m aro_cloud.admin grant-credits). Appends to the ledger; never edits it.
create or replace function grant_credits(p_user uuid, p_amount integer, p_note text)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  new_balance integer;
begin
  if p_amount <= 0 then
    raise exception 'amount must be positive';
  end if;
  perform ensure_user(p_user);
  update credit_accounts set balance = balance + p_amount, updated_at = now() where user_id = p_user returning balance into new_balance;
  insert into credit_ledger (user_id, kind, amount, balance_after, note) values (p_user, 'grant', p_amount, new_balance, p_note);
  return new_balance;
end;
$$;

revoke all on function ensure_user(uuid) from public, anon, authenticated;
revoke all on function grant_credits(uuid, integer, text) from public, anon, authenticated;
revoke all on function reserve_credits(uuid, uuid, integer) from public, anon, authenticated;
revoke all on function capture_credits(uuid, uuid) from public, anon, authenticated;
revoke all on function release_credits(uuid, uuid) from public, anon, authenticated;
-- Only the backend (service role) may call these three functions.

-- ----------------------------------------------------------------------------------------------- Row Level Security
alter table profiles        enable row level security;
alter table credit_accounts enable row level security;
alter table credit_ledger   enable row level security;
alter table usage_records   enable row level security;
alter table uploads         enable row level security;
alter table projects        enable row level security;
alter table assets          enable row level security;
alter table asset_versions  enable row level security;
alter table files           enable row level security;
alter table generation_jobs enable row level security;
alter table job_events      enable row level security;
alter table audit_log       enable row level security;   -- no policies: service role only
alter table model_registry  enable row level security;

create policy profiles_own on profiles for select using (user_id = (select auth.uid()));
create policy profiles_update_own on profiles for update using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));

-- Read-only for the owner; every write to money or jobs goes through the backend with the service role.
create policy credit_accounts_read on credit_accounts for select using (user_id = (select auth.uid()));
create policy credit_ledger_read   on credit_ledger   for select using (user_id = (select auth.uid()));
create policy usage_records_read   on usage_records   for select using (user_id = (select auth.uid()));
create policy uploads_read         on uploads         for select using (owner_id = (select auth.uid()));
create policy jobs_read            on generation_jobs for select using (owner_id = (select auth.uid()));
create policy job_events_read      on job_events      for select using (
  exists (select 1 from generation_jobs j where j.job_id = job_events.job_id and j.owner_id = (select auth.uid()))
);

-- Projects and assets: the owner has full control of their own rows.
create policy projects_own on projects for all using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy assets_own   on assets   for all using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
create policy versions_read on asset_versions for select using (owner_id = (select auth.uid()));
create policy files_read    on files          for select using (owner_id = (select auth.uid()));
-- Versions and files are created by the backend only (it verifies hashes and runs output validation first).

create policy model_registry_read on model_registry for select using (enabled);

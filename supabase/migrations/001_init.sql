-- Association Scraper schema for Supabase (PostgreSQL)
-- Apply this in the Supabase SQL editor or via the CLI.

create extension if not exists "pgcrypto";

create table if not exists associations (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    website_url text not null default '',
    enabled boolean not null default true,
    max_per_hour integer not null default 10,
    delay_min_seconds numeric not null default 5,
    delay_max_seconds numeric not null default 40,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists scraping_steps (
    id uuid primary key default gen_random_uuid(),
    association_id uuid not null references associations(id) on delete cascade,
    position integer not null,
    action text not null,
    locator_type text,
    locator_value text,
    params_json jsonb not null default '{}'::jsonb,
    enabled boolean not null default true,
    phase text not null default 'discovery'
        check (phase in ('discovery', 'record'))
);

create index if not exists scraping_steps_association_position_idx
    on scraping_steps (association_id, position);

-- Discovery / processing queue
create table if not exists records (
    id uuid primary key default gen_random_uuid(),
    association_id uuid not null references associations(id) on delete cascade,
    external_id text,
    source_url text not null,
    status text not null default 'pending'
        check (status in ('pending', 'in_progress', 'done', 'failed', 'skipped')),
    discovered_at timestamptz not null default now(),
    error text,
    unique (association_id, source_url)
);

create index if not exists records_association_status_idx
    on records (association_id, status);

-- Final scraped output: general columns + flexible JSONB
create table if not exists scraped_records (
    record_id uuid primary key default gen_random_uuid(),
    association_id uuid not null references associations(id) on delete cascade,
    source_url text not null,
    scraped_data jsonb not null default '{}'::jsonb,
    scraped_at timestamptz not null default now()
);

create index if not exists scraped_records_association_idx
    on scraped_records (association_id);

create table if not exists scrape_progress (
    association_id uuid primary key references associations(id) on delete cascade,
    hour_bucket_start timestamptz,
    hour_count integer not null default 0,
    last_run_at timestamptz,
    notes text
);

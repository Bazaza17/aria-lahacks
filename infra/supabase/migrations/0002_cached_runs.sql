-- Caches a successful agent run so subsequent demo runs can replay events
-- with original timing instead of hitting Anthropic live.

create table if not exists cached_runs (
  id uuid primary key default gen_random_uuid(),
  building_id uuid not null references buildings(id) on delete cascade,
  events jsonb not null,
  total_duration_ms int not null,
  tool_call_count int,
  iteration_count int,
  created_at timestamptz default now(),
  unique(building_id)
);

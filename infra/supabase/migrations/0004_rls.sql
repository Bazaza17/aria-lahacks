-- Row level security. The API uses the service role key, which bypasses RLS;
-- the web app uses the anon key and only needs to read buildings and preplans.
-- cached_runs and tool_calls get no policies, so only the service role can
-- reach them.

alter table buildings enable row level security;
alter table preplans enable row level security;
alter table cached_runs enable row level security;
alter table tool_calls enable row level security;

drop policy if exists "Public read buildings" on buildings;
create policy "Public read buildings" on buildings
  for select to anon, authenticated using (true);

drop policy if exists "Public read preplans" on preplans;
create policy "Public read preplans" on preplans
  for select to anon, authenticated using (true);

create table buildings (
  id uuid primary key default gen_random_uuid(),
  address text not null,
  lat double precision not null,
  lng double precision not null,
  scan_url text,
  is_demo boolean default false,
  created_at timestamptz default now()
);

create table preplans (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  scenario_params jsonb not null,
  report jsonb not null,
  created_at timestamptz default now()
);

create table tool_calls (
  id uuid primary key default gen_random_uuid(),
  preplan_id uuid references preplans(id) on delete cascade,
  iteration int not null,
  tool_name text not null,
  input jsonb,
  output jsonb,
  created_at timestamptz default now()
);

insert into buildings (address, lat, lng, is_demo)
values ('Hackathon Venue — Miami, FL', 25.7617, -80.1918, true);

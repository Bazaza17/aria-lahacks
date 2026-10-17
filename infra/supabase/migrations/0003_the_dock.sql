-- The Dock — hackathon demo building (400 NW 26th St, Miami, FL 33127).
-- Make it the ONLY demo building so the dashboard shows a single marker
-- at the real venue location.

update buildings
set is_demo = false
where id <> 'e5a3fddc-e22c-431c-a5d3-ee29ef8604d1';

insert into buildings (id, address, lat, lng, scan_url, is_demo)
values (
  'e5a3fddc-e22c-431c-a5d3-ee29ef8604d1',
  '400 NW 26th St, Miami, FL 33127',
  25.801267443503537,
  -80.20217163896397,
  'https://vsykrzfyvhnrwjyleywl.supabase.co/storage/v1/object/public/scans/the_dock/scan.glb',
  true
)
on conflict (id) do update set
  address = excluded.address,
  lat = excluded.lat,
  lng = excluded.lng,
  scan_url = excluded.scan_url,
  is_demo = true;

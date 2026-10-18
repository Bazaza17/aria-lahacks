-- The LA Hacks venue: James West Alumni Center, UCLA. Recreates the row the web app reads
-- (NEXT_PUBLIC_VENUE_BUILDING_ID = 547b5ec5-30c5-4f76-8080-012a52e90bd9). Safe to run twice.
--
-- Before running: replace YOUR-PROJECT-REF in scan_url with this project's ref, i.e. the
-- host of NEXT_PUBLIC_SUPABASE_URL. The mesh itself lives in the public `scans` bucket at
-- scans/james_west/venue_4rooms_web.glb (uploaded by hand; meshes never go in git).
--
-- It also clears is_demo on every other row, so the Miami placeholder that 0001 inserts
-- stays in the table but is never shown.

insert into buildings (id, address, lat, lng, scan_url, is_demo)
values (
  '547b5ec5-30c5-4f76-8080-012a52e90bd9',
  'James West Alumni Center, 325 Westwood Plaza, Los Angeles, CA 90095',
  34.07026948117506,
  -118.44520289359974,
  'https://YOUR-PROJECT-REF.supabase.co/storage/v1/object/public/scans/james_west/venue_4rooms_web.glb',
  true
)
on conflict (id) do update set
  address = excluded.address,
  lat = excluded.lat,
  lng = excluded.lng,
  -- keep a working scan_url if the row already has one (the placeholder never overwrites it)
  scan_url = coalesce(buildings.scan_url, excluded.scan_url),
  is_demo = true;

update buildings
set is_demo = false
where id <> '547b5ec5-30c5-4f76-8080-012a52e90bd9';

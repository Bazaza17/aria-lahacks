import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Resolved lazily (not at module load) so `next build` never crashes when the
// env vars aren't present at build time — they only need to exist at runtime.
function resolveEnv(): { url: string; anonKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error("Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY env vars");
  }
  return { url, anonKey };
}

export function getServerSupabase(): SupabaseClient {
  const { url, anonKey } = resolveEnv();
  return createClient(url, anonKey, {
    auth: { persistSession: false },
  });
}

let _browser: SupabaseClient | null = null;
export function getBrowserSupabase(): SupabaseClient {
  if (!_browser) {
    const { url, anonKey } = resolveEnv();
    _browser = createClient(url, anonKey);
  }
  return _browser;
}

export type Building = {
  id: string;
  address: string;
  lat: number;
  lng: number;
  scan_url: string | null;
  is_demo: boolean;
  created_at: string;
};

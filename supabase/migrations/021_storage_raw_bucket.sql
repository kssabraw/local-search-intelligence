-- Migration 021_storage_raw_bucket
-- SED Local Search Intelligence Platform -- immutable content-addressed raw Storage
--
-- Per ADR-0002: every provider response is preserved verbatim and immutably in
-- object storage (Supabase Storage for V1) at deterministic, content-addressed,
-- FAIL-ON-EXISTS paths, gzipped. The ops.raw_blob table stores hash/path/size
-- metadata; the bytes live in this private bucket.
--
-- Enforced by the collector (application layer), not the database:
--   * Path = content address, e.g.  <surface>/<sha256[:2]>/<sha256>.json.gz
--   * Upload with upsert=false (fail-on-exists); a colliding hash is a no-op,
--     never an overwrite (inverts the AR-Tools upsert:true convention).
--   * Payloads gzipped (Content-Encoding: gzip); ops.raw_blob.content_encoding='gzip'.
--
-- The bucket is PRIVATE (public=false): research raw evidence is never anon-readable.
-- Access is via the service-role key held only in Supabase/Railway secret management.
--
-- Guarded so this migration is a no-op on a plain Postgres (local validation)
-- where the Supabase `storage` schema is absent.

do $$
begin
  if exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('raw-observations', 'raw-observations', false, null, null)
    on conflict (id) do nothing;
    raise notice 'raw-observations private bucket ensured.';
  else
    raise notice 'storage schema absent; skipping bucket creation (non-Supabase environment).';
  end if;
end
$$;

-- Migration 001_extensions_and_schemas
-- SED Local Search Intelligence Platform -- physical schema v0.1
--
-- Mechanical split of supabase/schema/physical-schema-v0_1.sql (the
-- authoritative artifact) at the deployment-order boundaries declared in
-- docs/contracts/physical-schema-contract-v0_1.md section 36. See
-- supabase/migrations/README.md. Do NOT hand-edit; regenerate with
-- scripts/split_schema_to_migrations.py.
--
-- Research schemas are private: no grants to anon/authenticated are issued.
-- Product-facing RLS/auth is deferred to a later security contract (migration
-- 020_security in the contract's order; intentionally not created yet).

create extension if not exists pgcrypto;
create extension if not exists pg_trgm;
create extension if not exists vector;

create schema if not exists manifest;
create schema if not exists ops;
create schema if not exists core;
create schema if not exists maps;
create schema if not exists organic;
create schema if not exists aio;
create schema if not exists chatgpt;
create schema if not exists enrichment;
create schema if not exists research;
create schema if not exists client;

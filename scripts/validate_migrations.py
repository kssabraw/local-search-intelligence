#!/usr/bin/env python3
"""Apply all migrations to a throwaway local Postgres (with pgvector) and verify.

Creates an ephemeral PostgreSQL 16 cluster in a temp dir (initdb), starts it on a
private unix socket, applies supabase/migrations/*.sql in lexical order (each in
its own transaction with ON_ERROR_STOP), then runs reconciliation + integrity
checks:

  * pgvector / pg_trgm / pgcrypto installed
  * coordinate reconciliation: 1,100 -> 1,000 / 91 / 9
  * universe row counts (industries, markets, geometry, treatments, etc.)
  * append-only immutability trigger actually rejects UPDATE
  * research schemas hold no grants to anon/authenticated

Requires postgresql-16 + postgresql-16-pgvector on PATH (/usr/lib/postgresql/16/bin).
initdb/postgres cannot run as root, so if run as root it uses an unprivileged
user (default: 'postgres'). Exit code 0 on success.
"""
from __future__ import annotations
import os, pathlib, pwd, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
PGBIN = pathlib.Path(os.environ.get("PGBIN", "/usr/lib/postgresql/16/bin"))
RUN_AS = os.environ.get("PG_RUN_AS", "postgres")


def _demote(uid, gid, home):
    def fn():
        os.setgid(gid); os.setuid(uid); os.environ["HOME"] = home
    return fn


class PG:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="lsi-pgtest-"))
        self.data = self.dir / "data"
        self.sock = self.dir / "sock"
        self.sock.mkdir()
        self.preexec = None
        self.env = dict(os.environ)
        if os.geteuid() == 0:
            rec = pwd.getpwnam(RUN_AS)
            os.chown(self.dir, rec.pw_uid, rec.pw_gid)
            os.chown(self.sock, rec.pw_uid, rec.pw_gid)
            self.preexec = _demote(rec.pw_uid, rec.pw_gid, str(self.dir))
            self.env["HOME"] = str(self.dir)

    def run(self, *args, **kw):
        return subprocess.run(args, preexec_fn=self.preexec, env=self.env, **kw)

    def start(self):
        r = self.run(str(PGBIN / "initdb"), "-D", str(self.data), "-U", "postgres",
                     "--auth=trust", capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"initdb failed:\n{r.stderr}")
        # Redirect the server's own stdout/stderr to a logfile (-l). Capturing
        # pg_ctl's pipe here would deadlock: the daemonized postgres inherits the
        # pipe and never closes it, so subprocess.run would block on read forever.
        logfile = self.dir / "server.log"
        r = self.run(str(PGBIN / "pg_ctl"), "-D", str(self.data), "-w", "-t", "30",
                     "-l", str(logfile),
                     "-o", f"-k {self.sock} -c listen_addresses=''", "start",
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode:
            log = logfile.read_text() if logfile.exists() else "(no log)"
            raise SystemExit(f"pg_ctl start failed:\n{log}")

    def stop(self):
        self.run(str(PGBIN / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "stop",
                 capture_output=True, text=True)
        shutil.rmtree(self.dir, ignore_errors=True)

    def psql(self, sql=None, file=None, one_txn=False):
        cmd = [str(PGBIN / "psql"), "-h", str(self.sock), "-U", "postgres", "-d", "postgres",
               "-v", "ON_ERROR_STOP=1", "-tA"]
        if one_txn:
            cmd.append("-1")
        if file:
            cmd += ["-f", str(file)]
        else:
            cmd += ["-c", sql]
        return self.run(*cmd, capture_output=True, text=True)

    def val(self, sql):
        r = self.psql(sql)
        if r.returncode:
            raise SystemExit(f"query failed: {sql}\n{r.stderr}")
        return r.stdout.strip()


def main() -> int:
    pg = PG()
    try:
        print("initdb + start ephemeral cluster ...")
        pg.start()
        print(f"applying {len(MIGRATIONS)} migrations ...")
        for m in MIGRATIONS:
            r = pg.psql(file=m, one_txn=True)
            print(f"  {m.name:<45} {'ok' if r.returncode == 0 else 'FAIL'}")
            if r.returncode:
                sys.stderr.write(r.stderr)
                raise SystemExit(f"migration {m.name} failed")

        checks = []

        def check(label, sql, expected):
            got = pg.val(sql)
            checks.append((label, f"{got} (exp {expected})", "PASS" if str(got) == str(expected) else "FAIL"))

        check("extensions (vector,pg_trgm,pgcrypto)",
              "select count(*) from pg_extension where extname in ('vector','pg_trgm','pgcrypto')", 3)
        # 026 (ADR-0009) adds GEOGRID13E_V1: 650 coords (595 eligible / 50 water / 5 outside).
        # 1100 -> 1750, 1000 -> 1595, 91 -> 141, 9 -> 14.
        check("coordinates total", "select count(*) from manifest.market_coordinate", 1750)
        check("coordinates eligible_land",
              "select count(*) from manifest.market_coordinate where eligibility='eligible_land'", 1595)
        check("coordinates structural_water_exclusion",
              "select count(*) from manifest.market_coordinate where eligibility='structural_water_exclusion'", 141)
        check("coordinates outside_country_exclusion",
              "select count(*) from manifest.market_coordinate where eligibility='outside_country_exclusion'", 14)
        check("industries", "select count(*) from manifest.industry", 25)
        check("markets", "select count(*) from manifest.market", 50)
        check("methodology_industry", "select count(*) from manifest.methodology_industry", 25)
        check("methodology_market", "select count(*) from manifest.methodology_market", 50)
        # 019 seeds MAPORG13_V1 (13) + AIO9_V1 (9); 026 adds GEOGRID13E_V1 (13) -> 3 versions / 35 points.
        check("geometry_version", "select count(*) from manifest.geometry_version", 3)
        check("geometry_point", "select count(*) from manifest.geometry_point", 35)
        # 600 base (GOOGLE_QUERY_V1 100 + AIO_QUERY_V1 250 + CHATGPT_PROMPT_V1 250)
        # + 250 AIO_QUERY_V2 (migration 029) = 850.
        check("treatments", "select count(*) from manifest.treatment", 850)
        # 700 base + 250 aio->AIO_QUERY_V2 links (migration 029) = 950.
        check("surface_treatment", "select count(*) from manifest.surface_treatment", 950)
        check("AIO_QUERY_V2 treatments",
              "select count(*) from manifest.treatment where treatment_set_code='AIO_QUERY_V2'", 250)
        check("AIO_QUERY_V1 treatments retained",
              "select count(*) from manifest.treatment where treatment_set_code='AIO_QUERY_V1'", 250)
        # 4 seeded by 019 + DFS_MAPS_V2 (022, ADR-0006) + DFS_AIO_V2 (025, ADR-0008) = 6
        check("provider_profile", "select count(*) from manifest.provider_profile", 6)
        check("surface_config", "select count(*) from manifest.surface_config", 4)
        # ADR-0008: the AIO surface config is repointed DFS_AIO_V1 (ai_mode) -> DFS_AIO_V2 (organic ai_overview).
        check("aio surface_config -> DFS_AIO_V2",
              "select pp.profile_code from manifest.surface_config sc "
              "join manifest.surface s on s.surface_id=sc.surface_id "
              "join manifest.provider_profile pp on pp.provider_profile_id=sc.provider_profile_id "
              "where s.surface_code='aio'", "DFS_AIO_V2")
        # ADR-0009 (026): maps/organic/aio surface_config repointed to GEOGRID13E_V1.
        check("maps/organic/aio surface_config -> GEOGRID13E_V1",
              "select count(distinct gv.geometry_code) from manifest.surface_config sc "
              "join manifest.surface s on s.surface_id=sc.surface_id "
              "join manifest.geometry_version gv on gv.geometry_version_id=sc.geometry_version_id "
              "where s.surface_code in ('maps','organic','aio') and gv.geometry_code='GEOGRID13E_V1'", 1)
        check("surface_config on GEOGRID13E_V1 (count)",
              "select count(*) from manifest.surface_config sc "
              "join manifest.geometry_version gv on gv.geometry_version_id=sc.geometry_version_id "
              "where gv.geometry_code='GEOGRID13E_V1'", 3)
        check("panel_subset_industry (sentinel)", "select count(*) from manifest.panel_subset_industry", 5)
        check("panel_subset_market (sentinel)", "select count(*) from manifest.panel_subset_market", 10)
        check("surfaces seeded", "select count(*) from manifest.surface", 5)
        check("qa_contract_version", "select count(*) from ops.qa_contract_version", 1)
        check("qa_rule rows", "select count(*) from ops.qa_rule", 80)
        check("methodology_version frozen",
              "select count(*) from manifest.methodology_version where status='frozen' and frozen_at is not null", 1)

        # Insert a real row (row-level BEFORE UPDATE trigger only fires on matched rows),
        # then attempt to mutate it; the append-only trigger must reject it.
        pg.psql("insert into ops.raw_blob (sha256, storage_bucket, storage_path, byte_size, mime_type) "
                "values (repeat('a',64), 'raw-observations', 'test/a.json.gz', 1, 'application/json') "
                "on conflict do nothing")
        r = pg.psql("update ops.raw_blob set byte_size=2 where sha256 = repeat('a',64)")
        checks.append(("append-only trigger rejects UPDATE",
                       "rejected" if r.returncode else "ALLOWED", "PASS" if r.returncode else "FAIL"))
        d = pg.psql("delete from ops.raw_blob where sha256 = repeat('a',64)")
        checks.append(("append-only trigger rejects DELETE",
                       "rejected" if d.returncode else "ALLOWED", "PASS" if d.returncode else "FAIL"))

        priv = pg.val("""select count(*) from information_schema.role_table_grants
                         where grantee in ('anon','authenticated')
                           and table_schema in ('manifest','ops','core','maps','organic','aio',
                               'chatgpt','enrichment','research','client')""")
        checks.append(("no anon/authenticated grants on research schemas",
                       f"{priv} grants", "PASS" if priv == "0" else "FAIL"))

        print("\n" + f"{'check':<48} {'result':<22} status")
        print("-" * 84)
        failed = 0
        for label, result, status in checks:
            failed += status == "FAIL"
            print(f"{label:<48} {result:<22} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())

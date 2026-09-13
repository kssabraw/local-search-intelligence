"""Ephemeral local PostgreSQL 16 (+pgvector) cluster for offline validation.

Shared by scripts/validate_spike.py. initdb/postgres cannot run as root, so when
run as root it demotes to an unprivileged user (default 'postgres').
"""
from __future__ import annotations
import os, pathlib, pwd, shutil, subprocess, tempfile

PGBIN = pathlib.Path(os.environ.get("PGBIN", "/usr/lib/postgresql/16/bin"))
RUN_AS = os.environ.get("PG_RUN_AS", "postgres")


def _demote(uid, gid, home):
    def fn():
        os.setgid(gid); os.setuid(uid); os.environ["HOME"] = home
    return fn


class LocalPG:
    def __init__(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="lsi-spikepg-"))
        self.data = self.dir / "data"
        self.sock = self.dir / "sock"
        self.sock.mkdir()
        self.preexec = None
        self.env = dict(os.environ)
        if os.geteuid() == 0:
            rec = pwd.getpwnam(RUN_AS)
            for p in (self.dir, self.sock):
                os.chown(p, rec.pw_uid, rec.pw_gid)
            self.preexec = _demote(rec.pw_uid, rec.pw_gid, str(self.dir))
            self.env["HOME"] = str(self.dir)

    def _run(self, *args, **kw):
        return subprocess.run(args, preexec_fn=self.preexec, env=self.env, **kw)

    def start(self):
        r = self._run(str(PGBIN / "initdb"), "-D", str(self.data), "-U", "postgres",
                      "--auth=trust", capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"initdb failed:\n{r.stderr}")
        log = self.dir / "server.log"
        r = self._run(str(PGBIN / "pg_ctl"), "-D", str(self.data), "-w", "-t", "30", "-l", str(log),
                      "-o", f"-k {self.sock} -c listen_addresses=''", "start",
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode:
            raise SystemExit(f"pg_ctl start failed:\n{log.read_text() if log.exists() else ''}")

    def dsn(self) -> str:
        return f"host={self.sock} user=postgres dbname=postgres"

    def apply_migrations(self, migrations_dir: pathlib.Path):
        for m in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
            r = self._run(str(PGBIN / "psql"), "-h", str(self.sock), "-U", "postgres", "-d", "postgres",
                          "-1", "-v", "ON_ERROR_STOP=1", "-f", str(m), capture_output=True, text=True)
            if r.returncode:
                raise SystemExit(f"migration {m.name} failed:\n{r.stderr}")

    def stop(self):
        self._run(str(PGBIN / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "stop",
                  capture_output=True, text=True)
        shutil.rmtree(self.dir, ignore_errors=True)

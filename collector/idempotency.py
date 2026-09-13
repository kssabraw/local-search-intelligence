"""Deterministic idempotency key for a planned collection job.

job_key = sha256(methodology | wave | surface | industry | market | treatment |
coordinate | replicate). Guarantees at most one planned scientific collection
unit per (methodology, wave, surface, industry, market, treatment, coordinate,
replicate). A technical retry reuses the same job and never duplicates a paid
provider call (see CLAUDE.md conventions).
"""
from __future__ import annotations
import hashlib


def job_key(
    *,
    methodology_version_id: str,
    wave_id: str,
    surface_id: str,
    industry_id: str,
    market_id: str,
    surface_treatment_id: str,
    coordinate_id: str | None,
    replicate_no: int,
) -> str:
    parts = [
        methodology_version_id,
        wave_id,
        surface_id,
        industry_id,
        market_id,
        surface_treatment_id,
        coordinate_id or "no_coordinate",
        replicate_no,
    ]
    # ids may arrive as uuid.UUID from the DB; normalize every part to str.
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

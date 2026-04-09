"""
scripts/seed_sources.py

Transforms merged_master_sources.csv → data/sources_seed.json + data/sources_seed.csv
and optionally loads them into the database.

Usage:
    # Transform only (no DB):
    python -m scripts.seed_sources --transform-only

    # Transform + load into DB:
    python -m scripts.seed_sources

    # Load existing seed file (skip transform):
    python -m scripts.seed_sources --load-only
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from unidecode import unidecode

load_dotenv()

# Allow running as `python -m scripts.seed_sources` from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.db.connection import managed_connection
from ingestion.db.repository import upsert_source
from ingestion.models.source import SourceCreate

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CSV_INPUT = PROJECT_ROOT / "references" / "merged_master_sources.csv"
SEED_JSON = PROJECT_ROOT / "data" / "sources_seed.json"
SEED_CSV = PROJECT_ROOT / "data" / "sources_seed.csv"


# ─────────────────────────────────────────────
# FIELD TRANSFORMATIONS
# ─────────────────────────────────────────────

def make_canonical_key(name: str) -> str:
    """Slugify a source name into a stable machine-readable key."""
    transliterated = unidecode(name)
    slug = transliterated.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug


def parse_url_and_handle(url_or_handle: str, primary_platform: str) -> tuple[str | None, str | None]:
    """
    Split the mixed url_or_handle field into (url, handle).
    Heuristics based on content and platform.
    """
    v = url_or_handle.strip()
    if not v:
        return None, None

    # Explicit handle (@username)
    if v.startswith("@"):
        return None, v

    # t.me/channel_name
    if v.startswith("t.me/"):
        return f"https://{v}", f"@{v.split('t.me/')[-1]}"

    # LinkedIn search description — store as handle placeholder
    if v.lower().startswith("li search:") or v.lower().startswith("linkedin search:"):
        return None, v

    # Full URL
    if v.startswith("http://") or v.startswith("https://"):
        return v, None

    # Looks like a bare domain
    if "." in v and " " not in v and "/" not in v:
        return f"https://{v}", None

    # Path fragment (like "launches", "trending", "news")
    if "/" not in v and " " not in v and "." not in v:
        # Platform-specific base URLs
        platform_bases = {
            "FORUM": "https://news.ycombinator.com/",
            "WEB": "",
        }
        base = platform_bases.get(primary_platform.upper(), "")
        return (base + v if base else None), v

    # Domain with path
    if "." in v and " " not in v:
        return f"https://{v}", None

    # Fallback: treat as display handle / description
    return None, v


def parse_themes(raw: str) -> list[str]:
    """Split semicolon-separated themes into a list."""
    if not raw:
        return []
    return [t.strip() for t in raw.split(";") if t.strip()]


def parse_platforms(primary: str, secondary: str) -> list[str]:
    """Build a deduplicated list of all platforms."""
    platforms = [primary.strip()] if primary.strip() else []
    if secondary:
        for p in re.split(r"[,;]", secondary):
            p = p.strip()
            if p and p not in platforms:
                platforms.append(p)
    return platforms


def infer_fetch_method(primary_platform: str, source_type: str, url_or_handle: str) -> str:
    """
    Assign fetch_method based on primary platform, type, and handle.
    Heuristic-based — see comments for rationale.
    """
    p = primary_platform.upper().strip()
    u = url_or_handle.lower()

    if p == "TG":
        return "telegram_api"

    if p == "SB":  # Substack → RSS
        return "rss"

    if p == "POD":  # Podcast → RSS (all major podcasts publish RSS)
        return "rss"

    if p == "NEWS":  # Newsletter / news site → RSS
        return "rss"

    if p == "X":
        return "x_api"  # Wave 3 stub

    if p == "LI":
        return "linkedin_api"  # Wave 3 stub

    if p in ("FORUM", "COMM"):
        if "ycombinator" in u or u in ("launches", "news"):
            return "hn_api"
        if "reddit" in u:
            return "web_scraper"  # Reddit has API but not needed for MVP
        return "web_scraper"

    if p == "TOOL":
        return "site_change_monitor"

    if p == "DB/FEED":
        return "web_scraper"

    if p == "WEB":
        # Most blogs/media sites publish RSS — assume rss, note in fetch_config to verify
        return "rss"

    return "web_scraper"


def infer_wave(fetch_method: str) -> int:
    """Assign rollout wave based on fetch_method."""
    wave1 = {"rss", "telegram_api", "hn_api", "manual_import", "youtube_transcript"}
    wave3 = {"x_api", "linkedin_api"}
    if fetch_method in wave1:
        return 1
    if fetch_method in wave3:
        return 3
    return 2  # web_scraper, site_change_monitor, etc.


def infer_language(region: str) -> str | None:
    """
    Infer base language from region string.
    Stored separately from region for filtering flexibility.
    """
    region = region.lower()
    if region.startswith("en+ru") or region.startswith("ru/mixed") or "mixed" in region:
        return "mixed"
    if region.startswith("en"):
        return "en"
    if region.startswith("ru"):
        return "ru"
    return None


def normalize_monitoring_frequency(raw: str) -> str:
    """Normalize monitoring frequency to a clean value."""
    mapping = {
        "daily": "daily",
        "2-3x_week": "3x_week",
        "3x_week": "3x_week",
        "weekly": "weekly",
    }
    return mapping.get(raw.strip().lower(), raw.strip())


# ─────────────────────────────────────────────
# TRANSFORM
# ─────────────────────────────────────────────

# Known duplicates to remove (canonical_key values to deduplicate)
# We keep the first occurrence and skip subsequent ones.
_DEDUP_KEYS = {
    "reforge-blog-additional",  # exact duplicate of reforge-blog
    "ilya-krasinsky",           # lower-tier duplicate of ilja-krasinskij (RU entry)
}


def transform_csv(input_path: Path) -> list[dict]:
    records: list[dict] = []
    seen_keys: set[str] = set()

    with input_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source_name = row["source_name"].strip()
            if not source_name:
                continue

            primary_platform = row.get("primary_platform", "").strip()
            secondary_platforms = row.get("secondary_platforms", "").strip()
            url_or_handle = row.get("url_or_handle", "").strip()
            region = row.get("region", "").strip()

            url, handle = parse_url_and_handle(url_or_handle, primary_platform)
            platforms = parse_platforms(primary_platform, secondary_platforms)
            themes = parse_themes(row.get("themes", ""))
            fetch_method = infer_fetch_method(primary_platform, row.get("type", ""), url_or_handle)
            wave = infer_wave(fetch_method)
            language = infer_language(region)
            monitoring_frequency = normalize_monitoring_frequency(row.get("monitoring_frequency", ""))

            canonical_key = make_canonical_key(source_name)

            # Skip known duplicates
            if canonical_key in _DEDUP_KEYS or canonical_key in seen_keys:
                logger.info("Skipping duplicate: %s (%s)", source_name, canonical_key)
                continue
            seen_keys.add(canonical_key)

            record = {
                "source_name": source_name,
                "canonical_name": source_name,   # same by default; can be manually overridden
                "canonical_key": canonical_key,
                "source_type": row.get("type", "").strip() or "unknown",
                "region": region or None,
                "language": language,
                "primary_platform": primary_platform or None,
                "platforms": platforms,
                "url": url,
                "handle": handle,
                "themes": themes,
                "signal_type": row.get("signal_type", "").strip() or None,
                "signal_quality": _int_or_none(row.get("signal_quality")),
                "early_signal_potential": _int_or_none(row.get("early_signal_potential")),
                "startup_signal_value": _int_or_none(row.get("startup_signal_value")),
                "content_adaptation_value": _int_or_none(row.get("content_adaptation_value")),
                "brand_fit": _int_or_none(row.get("brand_fit")),
                "tier": _int_or_none(row.get("tier")) or 3,
                "wave": wave,
                "monitoring_frequency": monitoring_frequency or None,
                "fetch_method": fetch_method,
                "fetch_config": {},
                "is_active": True,
                "notes": row.get("why_relevant", "").strip() or None,
            }
            records.append(record)

    logger.info("Transformed %d sources (after dedup)", len(records))
    return records


def save_json(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    logger.info("Saved JSON: %s", path)


def save_csv(records: list[dict], path: Path) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    # Flatten list fields for CSV
    flat_records = []
    for r in records:
        flat = dict(r)
        flat["platforms"] = ";".join(r.get("platforms") or [])
        flat["themes"] = ";".join(r.get("themes") or [])
        flat["fetch_config"] = json.dumps(r.get("fetch_config") or {})
        flat_records.append(flat)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat_records[0].keys()))
        writer.writeheader()
        writer.writerows(flat_records)
    logger.info("Saved CSV: %s", path)


# ─────────────────────────────────────────────
# LOAD INTO DB
# ─────────────────────────────────────────────

def load_into_db(records: list[dict]) -> None:
    logger.info("Loading %d sources into database...", len(records))
    loaded = 0
    errors = 0

    with managed_connection() as conn:
        for record in records:
            try:
                source = SourceCreate(**record)
                source_id = upsert_source(conn, source)
                logger.debug("Upserted source: %s → %s", record["canonical_key"], source_id)
                loaded += 1
            except Exception as exc:
                logger.error("Failed to upsert %s: %s", record.get("canonical_key"), exc)
                errors += 1

    logger.info("DB load complete: %d loaded, %d errors", loaded, errors)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _int_or_none(value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sources registry from CSV")
    parser.add_argument("--transform-only", action="store_true",
                        help="Only transform and save seed files, skip DB load")
    parser.add_argument("--load-only", action="store_true",
                        help="Load existing data/sources_seed.json without re-transforming")
    parser.add_argument("--input", default=str(CSV_INPUT),
                        help=f"Input CSV path (default: {CSV_INPUT})")
    args = parser.parse_args()

    if args.load_only:
        if not SEED_JSON.exists():
            logger.error("Seed file not found: %s. Run without --load-only first.", SEED_JSON)
            sys.exit(1)
        with SEED_JSON.open(encoding="utf-8") as f:
            records = json.load(f)
        logger.info("Loaded %d records from %s", len(records), SEED_JSON)
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error("Input CSV not found: %s", input_path)
            sys.exit(1)
        records = transform_csv(input_path)
        save_json(records, SEED_JSON)
        save_csv(records, SEED_CSV)

    if not args.transform_only:
        load_into_db(records)


if __name__ == "__main__":
    main()

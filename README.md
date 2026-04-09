# Personal Brand Intelligence System — Ingestion Layer

Data ingestion backend for a personal brand intelligence pipeline.
Collects signals from curated sources (marketing, growth, GTM, AI, startups),
normalizes them into a unified format, and stores them in PostgreSQL.

This is the **data layer only** — no AI, no content generation, no agents.

---

## Architecture

```
sources (registry)
    │
    ▼
fetcher router
    │
    ├── rss.py           → Wave 1
    ├── telegram.py      → Wave 1
    ├── youtube.py       → Wave 1
    ├── hackernews.py    → Wave 1
    ├── web_scraper.py   → Wave 2
    ├── stubs.py (X, LinkedIn) → Wave 3
    │
    ▼
normalizer.py
    │  clean text, parse datetime, detect language, compute content_hash
    ▼
deduplicator.py
    │  hash-based cross-source dedup
    ▼
repository.py
    │  insert into content_items
    ▼
PostgreSQL (content_items)
```

### Status pipeline for content_items

```
new → normalized → deduplicated → filtered → candidate → selected → drafted → published
                                                                          ↑
                                                                       error (any stage)
```

---

## Project Structure

```
content-system/
├── ingestion/
│   ├── db/
│   │   ├── schema.sql         ← DDL: sources + content_items tables
│   │   ├── connection.py      ← psycopg v3 connection management
│   │   └── repository.py      ← CRUD operations
│   ├── models/
│   │   ├── source.py          ← Source / SourceCreate Pydantic models
│   │   └── content_item.py    ← ContentItem / RawFetchedItem models
│   ├── fetchers/
│   │   ├── base.py            ← BaseFetcher interface
│   │   ├── router.py          ← fetch_method → fetcher lookup
│   │   ├── rss.py             ← RSS / Atom (Wave 1, ✅ implemented)
│   │   ├── telegram.py        ← Telegram MTProto (Wave 1, ✅ implemented)
│   │   ├── youtube.py         ← YouTube transcripts (Wave 1, ✅ implemented)
│   │   ├── hackernews.py      ← HN public API (Wave 1, ✅ implemented)
│   │   ├── web_scraper.py     ← Static HTML scraper (Wave 2, ✅ skeleton)
│   │   ├── manual_import.py   ← JSON/CSV import (Wave 1, ✅ implemented)
│   │   └── stubs.py           ← X API, LinkedIn API (Wave 3, 🔲 stubs)
│   ├── normalizer.py          ← Text cleaning, datetime parsing, hashing
│   ├── deduplicator.py        ← Hash-based dedup
│   └── pipeline.py            ← Orchestration: fetch → normalize → dedup → save
├── scripts/
│   ├── seed_sources.py        ← Transform CSV → seed files → load into DB
│   └── run_ingestion.py       ← CLI runner
├── data/
│   ├── sources_seed.json      ← Generated: transformed source registry
│   └── sources_seed.csv       ← Generated: same in CSV format
├── references/
│   ├── merged_master_sources.csv  ← Source shortlist input
│   └── merged_master_sources.md
├── .env.example
├── requirements.txt
└── README.md
```

---

## Setup

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment variables

```bash
cp .env.example .env
# Edit .env — set DATABASE_URL at minimum
```

### 3. Database

Works with local PostgreSQL or Supabase (free tier is sufficient).

```bash
# Apply schema:
psql $DATABASE_URL -f ingestion/db/schema.sql

# Or in Supabase: paste schema.sql into the SQL editor
```

### 4. Telegram setup (first time only)

If you plan to use `telegram_api` fetcher:

```bash
# Run this once to create the session file:
python -c "
from telethon.sync import TelegramClient
import os; from dotenv import load_dotenv; load_dotenv()
client = TelegramClient('telegram.session', int(os.environ['TELEGRAM_API_ID']), os.environ['TELEGRAM_API_HASH'])
client.start(phone=os.environ.get('TELEGRAM_PHONE'))
print('Session created.')
"
```

---

## Loading Sources

Transform and load `merged_master_sources.csv` into the `sources` table:

```bash
# Transform only (inspect output before loading):
python -m scripts.seed_sources --transform-only
# → generates data/sources_seed.json and data/sources_seed.csv

# Transform + load into DB:
python -m scripts.seed_sources

# Re-load without re-transforming:
python -m scripts.seed_sources --load-only
```

The seed script applies the following transformations:
- Splits `url_or_handle` → `url` + `handle`
- Generates `canonical_key` (slugified, transliterated)
- Infers `fetch_method` from platform type
- Infers `wave` (1/2/3) from fetch_method
- Infers `language` from region (separate field)
- Builds `platforms` array from primary + secondary
- Removes known duplicates (Reforge Blog ×2, Ilya Krasinsky ×2)
- Sets `is_active=true` for all sources by default

---

## Running Ingestion

```bash
# Run all Wave 1 sources (RSS, Telegram, HN, YouTube, manual):
python -m scripts.run_ingestion --wave 1

# Run all RSS sources:
python -m scripts.run_ingestion --method rss

# Run a single source:
python -m scripts.run_ingestion --source casey-winters

# Run everything:
python -m scripts.run_ingestion --all

# Dry run (fetch + normalize, no DB write):
python -m scripts.run_ingestion --wave 1 --dry-run
```

### Cron example

```bash
# Run Wave 1 daily at 08:00
0 8 * * * cd /path/to/content-system && .venv/bin/python -m scripts.run_ingestion --wave 1 >> logs/ingestion.log 2>&1
```

---

## Fetch Methods

| Method | Wave | Status | Notes |
|---|---|---|---|
| `rss` | 1 | ✅ Implemented | feedparser, handles RSS + Atom |
| `telegram_api` | 1 | ✅ Implemented | telethon MTProto, public channels |
| `youtube_transcript` | 1 | ✅ Implemented | No API key needed for transcripts |
| `hn_api` | 1 | ✅ Implemented | HN public Firebase API |
| `manual_import` | 1 | ✅ Implemented | JSON or CSV file import |
| `web_scraper` | 2 | ✅ Skeleton | httpx + bs4, static HTML only |
| `site_change_monitor` | 2 | ✅ Skeleton | Same as web_scraper, dedup detects changes |
| `x_api` | 3 | 🔲 Stub | Raises FetchError until implemented |
| `linkedin_api` | 3 | 🔲 Stub | Raises FetchError until implemented |

---

## Adding a New Source Manually

```python
from ingestion.db.connection import managed_connection
from ingestion.db.repository import upsert_source
from ingestion.models.source import SourceCreate

with managed_connection() as conn:
    upsert_source(conn, SourceCreate(
        source_name="My New Source",
        canonical_name="My New Source",
        canonical_key="my-new-source",
        source_type="media",
        primary_platform="WEB",
        platforms=["WEB"],
        url="https://example.com/feed.xml",
        fetch_method="rss",
        themes=["growth", "GTM"],
        tier=2,
        wave=1,
        is_active=True,
    ))
```

---

## Defaults and Assumptions

Sources where fetch method could not be clearly determined default to `rss` (for WEB platform)
or `web_scraper`. Review `data/sources_seed.json` after transform and adjust `fetch_config`
for sources that need custom RSS URLs or scraping selectors.

**Sources that need manual fetch_config adjustment after seeding:**
- Sources with `primary_platform=WEB` and no obvious RSS feed → set `fetch_method=web_scraper`
- YouTube sources → add `fetch_config.video_ids` or `fetch_config.channel_id`
- Telegram sources with custom channel names → verify `handle` field
- LinkedIn sources → Wave 3, currently stubs
- X sources → Wave 3, currently stubs

---

## TODO — Next Phase

- [ ] AI analysis layer: topic clustering, signal scoring, brand fit classification
- [ ] Feed URL discovery: auto-detect RSS from WEB sources (check `/feed`, `/rss`, `<link rel="alternate">`)
- [ ] Telegram: save `min_id` after each run for incremental fetching
- [ ] YouTube: channel video listing via YouTube Data API
- [ ] Product Hunt scraper (COMM type)
- [ ] Indie Hackers scraper
- [ ] Crunchbase / Dealroom integration
- [ ] X API (Wave 3) — requires developer account
- [ ] LinkedIn (Wave 3) — evaluate Playwright-based approach
- [ ] Metrics dashboard: ingestion counts by source, error rates
- [ ] Retry logic with exponential backoff for transient fetch errors
- [ ] Webhook trigger option (instead of cron-only)

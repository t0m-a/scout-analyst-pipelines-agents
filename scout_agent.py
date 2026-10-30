#!/usr/bin/env python3
"""
SCOUT Agent v4.0.0 — Automated Multi-Track Lead Aggregation Engine
Dependencies: Python 3.10+ Standard Library ONLY (Zero external pip packages)

Supports 73+ Global Platforms across 6 Strategic Tracks:
  - Track A: Direct B2B & Fractional MSP (6 Portals)
  - Track B: Category 1 — AI Training, RLHF & Technical Logic Evaluation (20 Portals)
  - Track C: Category 2 — Vetted Global & Nearshore LATAM Tech Networks (16 Networks)
  - Track D: Category 3 — Francophone & European IT/Cloud Marketplaces (9 Portals)
  - Track E: Category 5 — Executive Expert Networks ($150-$400/hr Micro-Advisory Calls)
  - Track F: Category 6 — Curated Remote-First & Work-From-Anywhere Job Boards (JSON APIs, RSS, Dorks)

New in v4.0.0:
  - Dead-platform circuit breaker (automatically blocks joinstellar.ai / Stellar AI).
  - Clustered Portal Dorking (`--mode clustered` default vs `--mode individual`) to prevent
    HTTP 429/202 search-engine rate-limiting across 58+ walled portals.
  - Declarative CLI commands: `run`, `list-platforms` (alias `list`), `add-platform`, `add-keyword`,
    `seed-verified`.
"""

import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "platforms_config.json"
DB_PATH = BASE_DIR / "career_ops.db"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

REQUIRED_COLUMNS = {
    "id": "INTEGER",
    "job_hash": "TEXT",
    "platform_id": "TEXT",
    "platform_name": "TEXT",
    "category": "TEXT",
    "track": "TEXT",
    "contract_caveat": "TEXT DEFAULT 'fractional_or_fulltime'",
    "title": "TEXT",
    "company": "TEXT",
    "location": "TEXT",
    "url": "TEXT",
    "description": "TEXT",
    "tags": "TEXT",
    "published_at": "TEXT",
    "published_date": "TEXT",
    "discovered_at": "TEXT",
    "status": "TEXT DEFAULT 'NEW'",
    "verdict": "TEXT DEFAULT NULL",
    "total_score": "INTEGER DEFAULT NULL",
    "tech_score": "INTEGER DEFAULT NULL",
    "safety_score": "INTEGER DEFAULT NULL",
    "geo_lang_score": "INTEGER DEFAULT NULL",
    "contract_score": "INTEGER DEFAULT NULL",
    "matched_skills": "TEXT DEFAULT NULL",
    "missing_gaps": "TEXT DEFAULT NULL",
    "red_flags": "TEXT DEFAULT NULL",
    "analyst_notes": "TEXT DEFAULT NULL",
    "proposal_en": "TEXT DEFAULT NULL",
    "proposal_fr": "TEXT DEFAULT NULL",
    "proposal_es": "TEXT DEFAULT NULL",
    "proposal_advisory": "TEXT DEFAULT NULL",
}


def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_hash TEXT UNIQUE NOT NULL,
            platform_id TEXT,
            platform_name TEXT,
            category TEXT,
            track TEXT,
            contract_caveat TEXT DEFAULT 'fractional_or_fulltime',
            title TEXT NOT NULL,
            company TEXT,
            location TEXT,
            url TEXT,
            description TEXT,
            tags TEXT,
            published_at TEXT,
            published_date TEXT,
            discovered_at TEXT NOT NULL,
            status TEXT DEFAULT 'NEW',
            verdict TEXT DEFAULT NULL,
            total_score INTEGER DEFAULT NULL,
            tech_score INTEGER DEFAULT NULL,
            safety_score INTEGER DEFAULT NULL,
            geo_lang_score INTEGER DEFAULT NULL,
            contract_score INTEGER DEFAULT NULL,
            matched_skills TEXT DEFAULT NULL,
            missing_gaps TEXT DEFAULT NULL,
            red_flags TEXT DEFAULT NULL,
            analyst_notes TEXT DEFAULT NULL,
            proposal_en TEXT DEFAULT NULL,
            proposal_fr TEXT DEFAULT NULL,
            proposal_es TEXT DEFAULT NULL,
            proposal_advisory TEXT DEFAULT NULL
        )
        """
    )
    existing_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()
    }
    for col_name, col_def in REQUIRED_COLUMNS.items():
        if col_name not in existing_cols and col_name != "id":
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col_name} {col_def}")
    conn.commit()
    return conn


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg: dict, config_path: Path = CONFIG_PATH) -> None:
    cfg["last_updated"] = datetime.date.today().isoformat()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def strip_html(raw_text: str) -> str:
    if not raw_text:
        return ""
    unescaped = html.unescape(str(raw_text))
    cleaned = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", cleaned).strip()


def compute_hash(title: str, company: str, url: str) -> str:
    norm_title = re.sub(r"\s+", " ", title.strip().lower()).strip()
    payload = f"{norm_title}|{company.strip().lower()}|{url.strip().lower()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def is_dead_platform(url: str, title: str, cfg: dict) -> bool:
    combined = f"{url} {title}".lower()
    for dead in cfg.get("dead_platforms_blacklist", []):
        domain = dead.get("domain", "").lower()
        name = dead.get("name", "").lower()
        if (domain and domain in combined) or (name and name in combined):
            return True
    return False


def passes_global_pre_filter(item: dict, cfg: dict, bypass_keyword_check: bool = False) -> bool:
    if is_dead_platform(item.get("url", ""), item.get("title", ""), cfg):
        return False
    if bypass_keyword_check:
        return True

    params = cfg.get("global_parameters", {})
    hard_excludes = [k.lower() for k in params.get("hard_exclude_keywords", [])]
    loc_blacklist = [k.lower() for k in params.get("location_blacklist", [])]
    must_match = [k.lower() for k in params.get("must_match_any_keyword", [])]

    blob = " ".join(
        [
            str(item.get("title", "")),
            str(item.get("company", "")),
            str(item.get("description", "")),
            str(item.get("tags", "")),
            str(item.get("location", "")),
        ]
    ).lower()

    loc_str = str(item.get("location", "")).lower()
    for loc_bad in loc_blacklist:
        if loc_bad in loc_str or loc_bad in blob:
            return False

    for bad in hard_excludes:
        if bad in blob:
            # Allow negated red flags like "no tier 1 helpdesk"
            neg_pattern = r"(?:no|zero|without|never|not)\s+(?:[a-z0-9/-]+\s+){0,3}" + re.escape(bad)
            if not re.search(neg_pattern, blob):
                return False

    if bypass_keyword_check:
        return True

    return any(kw in blob for kw in must_match)


def http_get(url: str, timeout: int = 12) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/xml, text/xml, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9,fr;q=0.8,es;q=0.7",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_json_api(platform: dict) -> list:
    url = platform["url"]
    raw = http_get(url)
    data = json.loads(raw.decode("utf-8", errors="replace"))

    root_key = platform.get("json_root_key")
    records = data.get(root_key, []) if root_key and isinstance(data, dict) else data
    if not isinstance(records, list):
        return []

    fmap = platform.get("field_mapping", {})
    results = []
    for row in records:
        if not isinstance(row, dict):
            continue
        # RemoteOK first element is often legal metadata
        if "title" not in row and "position" not in row and "jobTitle" not in row:
            continue

        title = strip_html(row.get(fmap.get("title", "title"), ""))
        if not title:
            continue
        company = strip_html(row.get(fmap.get("company", "company"), platform["name"]))
        desc = strip_html(row.get(fmap.get("description", "description"), ""))[:1500]
        job_url = str(row.get(fmap.get("url", "url"), platform["url"]))
        if job_url.startswith("/"):
            job_url = f"https://{platform.get('domain', '')}{job_url}"

        loc_val = row.get(fmap.get("location", "location"), "Remote Worldwide")
        if isinstance(loc_val, list):
            loc_val = ", ".join(str(x) for x in loc_val) if loc_val else "Remote Worldwide"
        tags_val = row.get(fmap.get("tags", "tags"), "")
        if isinstance(tags_val, list):
            tags_val = ", ".join(str(x) for x in tags_val)

        pub = str(row.get(fmap.get("published_at", fmap.get("date", "published_at")), datetime.date.today().isoformat()))

        results.append(
            {
                "platform_id": platform["id"],
                "platform_name": platform["name"],
                "category": platform.get("category", "Category 6: Curated Remote-First Job Boards"),
                "track": platform.get("track", "Track F: Curated Remote-First & WFA Job Boards"),
                "contract_caveat": platform.get("contract_caveat", "fractional_or_fulltime"),
                "title": title,
                "company": company or platform["name"],
                "location": str(loc_val or "Remote Worldwide"),
                "url": job_url,
                "description": desc,
                "tags": str(tags_val),
                "published_at": pub,
            }
        )
    return results


def fetch_rss_feed(platform: dict) -> list:
    raw = http_get(platform["url"])
    root = ET.fromstring(raw)
    results = []

    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    for item in items[:50]:
        title_el = item.find("title")
        if title_el is None:
            title_el = item.find("{http://www.w3.org/2005/Atom}title")
        link_el = item.find("link")
        if link_el is None:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
        desc_el = item.find("description")
        if desc_el is None:
            desc_el = item.find("{http://www.w3.org/2005/Atom}summary")
        pub_el = item.find("pubDate")
        region_el = item.find("region")

        title_raw = title_el.text if title_el is not None and title_el.text else ""
        title = strip_html(title_raw)
        if not title:
            continue

        company = platform["name"]
        if ":" in title:
            parts = title.split(":", 1)
            company = parts[0].strip()
            title = parts[1].strip()

        link = ""
        if link_el is not None:
            link = link_el.text.strip() if link_el.text else link_el.attrib.get("href", "")

        desc = strip_html(desc_el.text if desc_el is not None and desc_el.text else "")[:1500]
        pub = pub_el.text.strip() if pub_el is not None and pub_el.text else datetime.date.today().isoformat()
        loc = region_el.text.strip() if region_el is not None and region_el.text else "Remote Worldwide"

        results.append(
            {
                "platform_id": platform["id"],
                "platform_name": platform["name"],
                "category": platform.get("category", "Category 6: Curated Remote-First Job Boards"),
                "track": platform.get("track", "Track F: Curated Remote-First & WFA Job Boards"),
                "contract_caveat": platform.get("contract_caveat", "fractional_or_fulltime"),
                "title": title,
                "company": company,
                "location": loc,
                "url": link or platform["url"],
                "description": desc,
                "tags": "rss, remote",
                "published_at": pub,
            }
        )
    return results


def fetch_portal_dork(platform: dict) -> list:
    query = platform.get("search_query", f"site:{platform.get('domain', '')} remote")
    encoded_q = urllib.parse.quote_plus(query)
    ddg_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
    raw = http_get(ddg_url)
    page = raw.decode("utf-8", errors="replace")

    results = []
    block_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    for match in block_pattern.finditer(page):
        raw_href, raw_title, raw_snippet = match.groups()
        if "uddg=" in raw_href:
            parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
            clean_url = parsed_qs.get("uddg", [raw_href])[0]
        else:
            clean_url = html.unescape(raw_href)

        title = strip_html(raw_title)
        snippet = strip_html(raw_snippet)
        if not title:
            continue

        results.append(
            {
                "platform_id": platform["id"],
                "platform_name": platform["name"],
                "category": platform.get("category", "Portal Dork"),
                "track": platform.get("track", "Track B: Async AI Evaluation & RLHF"),
                "contract_caveat": platform.get("contract_caveat", "async_flexible"),
                "title": title,
                "company": platform["name"],
                "location": "Remote / Global",
                "url": clean_url,
                "description": f"{snippet} | Portal Strategy: {platform.get('notes', '')}",
                "tags": platform.get("category", ""),
                "published_at": datetime.date.today().isoformat(),
            }
        )
    return results


def fetch_clustered_portal_dorks(platforms: list, delay_sec: float = 1.2) -> list:
    """
    Groups portal_dork platforms into chunks of 5 domains per query to prevent
    DuckDuckGo HTTP 429 rate-limiting while scanning all 58+ walled portals.
    """
    dork_platforms = [
        p for p in platforms
        if p.get("enabled", True) and (p.get("type") or p.get("connector_type")) == "portal_dork"
    ]
    domain_map = {p.get("domain", "").lower(): p for p in dork_platforms if p.get("domain")}

    results = []
    chunk_size = 5
    for idx in range(0, len(dork_platforms), chunk_size):
        chunk = dork_platforms[idx : idx + chunk_size]
        sites_expr = " OR ".join(f"site:{p['domain']}" for p in chunk if p.get("domain"))
        if not sites_expr:
            continue
        cluster_query = (
            f"({sites_expr}) "
            f"(\"Azure\" OR \"M365\" OR \"Entra\" OR \"SysAdmin\" OR \"Cloud\" OR \"MSP\" "
            f"OR \"Python\" OR \"AI Trainer\" OR \"RLHF\" OR \"French\" OR \"Spanish\" OR \"Télétravail\")"
        )
        synthetic_platform = {
            "id": "cluster_dork",
            "name": chunk[0]["name"],
            "category": chunk[0].get("category", ""),
            "track": chunk[0].get("track", ""),
            "contract_caveat": chunk[0].get("contract_caveat", "async_flexible"),
            "search_query": cluster_query,
            "notes": chunk[0].get("notes", ""),
        }
        try:
            hits = fetch_portal_dork(synthetic_platform)
            for h in hits:
                matched_p = chunk[0]
                url_lower = h["url"].lower()
                for dom, p_obj in domain_map.items():
                    if dom in url_lower:
                        matched_p = p_obj
                        break
                h["platform_id"] = matched_p["id"]
                h["platform_name"] = matched_p["name"]
                h["category"] = matched_p.get("category", "")
                h["track"] = matched_p.get("track", "")
                h["contract_caveat"] = matched_p.get("contract_caveat", "async_flexible")
                h["company"] = matched_p["name"]
                h["description"] = f"{h['description']} | Strategy: {matched_p.get('notes', '')}"
                results.append(h)
        except Exception as exc:
            print(f"[SCOUT WARN] Cluster dork batch {idx // chunk_size + 1} error: {exc}")
        time.sleep(delay_sec)
    return results


def insert_opportunities(conn: sqlite3.Connection, items: list, cfg: dict, bypass_filter: bool = False) -> int:
    inserted = 0
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")
    for item in items:
        if not passes_global_pre_filter(item, cfg, bypass_keyword_check=bypass_filter):
            continue

        pid = item.get("platform_id", "")
        jhash = compute_hash(item["title"], item["company"], item["url"])
        cur = conn.execute("SELECT 1 FROM opportunities WHERE job_hash = ?", (jhash,))
        if cur.fetchone():
            continue

        pub_date = item.get("published_at") or item.get("published_date") or now_iso[:10]
        conn.execute(
            """
            INSERT INTO opportunities (
                job_hash, platform_id, platform_name, category, track, contract_caveat,
                title, company, location, url, description, tags, published_at, published_date,
                discovered_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW')
            """,
            (
                jhash,
                pid,
                item.get("platform_name", ""),
                item.get("category", ""),
                item.get("track", ""),
                item.get("contract_caveat", "fractional_or_fulltime"),
                item["title"],
                item.get("company", ""),
                item.get("location", "Remote Worldwide"),
                item.get("url", ""),
                item.get("description", ""),
                item.get("tags", ""),
                pub_date,
                pub_date,
                now_iso,
            ),
        )
        inserted += 1
    conn.commit()
    return inserted


def seed_verified_baseline(conn: sqlite3.Connection, cfg: dict) -> int:
    """
    Seeds high-signal baseline opportunities across all 6 tracks (plus a test low-fit row
    and a full-time caveat row) so offline environments and initial installations can verify
    the full 6-track scoring & outreach proposal pipeline immediately.
    """
    today = datetime.date.today().isoformat()
    samples = [
        # Track A: Direct B2B & Fractional MSP / Upwork
        {
            "platform_id": "upwork_msp",
            "platform_name": "Upwork (Managed Services & Cloud)",
            "category": "Category 4: Direct-to-Client & Fractional MSP",
            "track": "Track A: Direct B2B & Fractional MSP",
            "contract_caveat": "fractional_friendly",
            "title": "Fractional NOC / Centralized Services Engineer (Liongard, IT Glue, Autotask, M365)",
            "company": "North American Growth MSP (via Upwork)",
            "location": "Remote Americas (UTC-5 / EST)",
            "url": "https://www.upwork.com/freelance-jobs/managed-services/",
            "description": (
                "Seeking a senior fractional Centralized Services / NOC Engineer for 20 hours/week ($35-$55/hr) "
                "to standardize Liongard inspectors, IT Glue documentation, Autotask PSA alerting workflows, "
                "NinjaOne RMM scripting, Acronis BCDR verification, and Microsoft Entra ID Conditional Access. "
                "100% asynchronous project execution; focus on infrastructure architecture, automation, and proactive monitoring."
            ),
            "tags": "liongard, it glue, autotask, ninjaone, entra id, m365, acronis, fractional, async",
            "published_at": today,
        },
        # Track B: Category 1 — AI Training & RLHF (Outlier, Mercor, Alignerr, Mindrift)
        {
            "platform_id": "outlier_ai",
            "platform_name": "Outlier AI",
            "category": "Category 1: AI Training & RLHF",
            "track": "Track B: Async AI Evaluation & RLHF",
            "contract_caveat": "async_flexible",
            "title": "Technical AI Trainer & Systems Logic Evaluator (French / Spanish / English)",
            "company": "Outlier AI (Infrastructure & Squad Reviewer Track)",
            "location": "Global Remote (Self-Paced Async)",
            "url": "https://outlier.ai/",
            "description": (
                "Evaluate frontier LLM responses on Cloud Infrastructure (Azure, M365, Entra ID), Linux/Debian "
                "system administration, network security, and Python automation scripts across French, Spanish, "
                "and English. Self-paced asynchronous RLHF rubric grading and technical writing verification."
            ),
            "tags": "ai trainer, rlhf, french, spanish, azure, linux, python, async, self-paced",
            "published_at": today,
        },
        {
            "platform_id": "mercor",
            "platform_name": "Mercor",
            "category": "Category 1: AI Training & RLHF",
            "track": "Track B: Async AI Evaluation & RLHF",
            "contract_caveat": "async_flexible",
            "title": "Senior Cloud Infrastructure & Security Rubric Architect (RLHF / Agentic Evaluation)",
            "company": "Mercor AI Lab Partner",
            "location": "Worldwide Remote (Contractor, Flexible Hours)",
            "url": "https://mercor.com/",
            "description": (
                "Design multi-step evaluation rubrics and red-team agentic MCP workflows for enterprise cloud "
                "administration (Azure, M365, Entra ID, PowerShell, Linux, Python, Ollama). $65-$110/hr, "
                "asynchronous self-paced blocks (15-25 hours/week)."
            ),
            "tags": "ai evaluator, rlhf, rubric, mcp, azure, entra id, powershell, python, async, part-time",
            "published_at": today,
        },
        # Track C: Category 2 — Vetted Global & Nearshore Networks
        {
            "platform_id": "neuronhire",
            "platform_name": "NeuronHire",
            "category": "Category 2: Vetted Global & LATAM Tech Networks",
            "track": "Track C: Vetted Global & Nearshore LATAM Networks",
            "contract_caveat": "fractional_or_fulltime",
            "title": "Remote AI Context Engineer & Cloud Automation Specialist",
            "company": "NeuronHire Nearshore Enterprise Partner",
            "location": "Global Remote (Americas)",
            "url": "https://www.neuronhire.com/",
            "description": (
                "Contract opportunity for a bilingual Systems & AI Context Engineer. "
                "Build RAG/MCP context pipelines with Python, Pandas, Ollama, and LangChain while auditing "
                "Azure and Microsoft 365 cloud security telemetry. Flexible fractional contract (20 hours/week)."
            ),
            "tags": "context engineer, python, pandas, ollama, langchain, mcp, azure, m365, fractional",
            "published_at": today,
        },
        # Track D: Category 3 — Francophone & European IT Marketplaces (Free-Work, Malt, Freelancermap)
        {
            "platform_id": "free_work_fr",
            "platform_name": "Free-Work (ex Freelance-Info)",
            "category": "Category 3: Francophone & European IT Portals",
            "track": "Track D: Francophone & European IT/Cloud Marketplaces",
            "contract_caveat": "fractional_friendly",
            "title": "Ingénieur Cloud Microsoft 365 / Entra ID / Intune & Automatisation (100% Télétravail)",
            "company": "Cabinet Conseil Cloud & Cybersécurité (via Free-Work / Malt)",
            "location": "100% Télétravail International (Francophone / Remote)",
            "url": "https://www.free-work.com/",
            "description": (
                "Mission freelance à temps partiel (20h/semaine, asynchrone) pour un Administrateur Systèmes / "
                "Ingénieur Cloud senior francophone. Audit de sécurité Microsoft 365, durcissement Entra ID "
                "(Conditional Access), Intune, sauvegarde Acronis/Veeam BCDR, scripts PowerShell/Python et "
                "documentation technique (FR/EN)."
            ),
            "tags": "français, french, télétravail, administrateur systèmes, ingénieur cloud, m365, entra id, intune, powershell, acronis",
            "published_at": today,
        },
        # Track E: Category 5 — Executive Expert Networks (GLG / AlphaSights)
        {
            "platform_id": "glg_insights",
            "platform_name": "GLG (Gerson Lehrman Group)",
            "category": "Category 5: Executive Expert Networks",
            "track": "Track E: Executive Expert Networks ($150-$400/hr Calls)",
            "contract_caveat": "micro_advisory",
            "title": "Paid 60-Min Executive Consultation: MSP MDR/ITDR & RMM Vendor Landscape (Huntress, Blackpoint, Acronis)",
            "company": "GLG Institutional Tech Research Practice",
            "location": "Remote Telephone / Video Consultation (Global)",
            "url": "https://glginsights.com/council-members/",
            "description": (
                "Seeking a Senior NOC / MSP Infrastructure Consultant managing 1,500+ endpoints to provide a "
                "60-minute market and operational assessment ($250/hr honorarium) comparing Huntress Managed EDR/ITDR, "
                "Blackpoint Cyber CompassOne, SentinelOne Vigilance, Acronis Cyber Protect, SaaS Alerts, and Augmentt "
                "alongside Liongard, IT Glue, and Autotask PSA integrations."
            ),
            "tags": "advisory, consultation, msp, mssp, huntress, blackpoint, acronis, sentinelone, liongard, it glue, autotask",
            "published_at": today,
        },
        # Track F: Category 6 — Curated Remote Boards (4DayWeek.io + DistantJob Full-Time Caveat + Low Fit test)
        {
            "platform_id": "4dayweek_io",
            "platform_name": "4 Day Week (4DayWeek.io)",
            "category": "Category 6: Curated Remote-First Job Boards",
            "track": "Track F: Curated Remote-First & WFA Job Boards",
            "contract_caveat": "fractional_friendly",
            "title": "Senior Cloud Infrastructure & Python Automation Engineer (4-Day Week / Async)",
            "company": "Distributed Cloud Ops Co.",
            "location": "Work From Anywhere / Global Remote",
            "url": "https://4dayweek.io/",
            "description": (
                "4 day week (28h/wk) asynchronous contractor role. Automate Microsoft Azure, Entra ID, Cloudflare edge, "
                "and Linux/Debian infrastructure monitoring using Python, Pandas, and Graph API. Flat hierarchy, "
                "comprehensive documentation culture, flexible schedule."
            ),
            "tags": "4 day week, async, azure, entra id, cloudflare, linux, debian, python, pandas, graph api",
            "published_at": today,
        },
        {
            "platform_id": "distantjob",
            "platform_name": "DistantJob (Full-Time Agency Caveat)",
            "category": "Category 6: Curated Remote-First Job Boards",
            "track": "Track F: Curated Remote-First & WFA Job Boards",
            "contract_caveat": "full_time_only",
            "title": "Principal AI Solutions & Cloud Infrastructure Consultant (Full-Time Remote)",
            "company": "DistantJob Remote Recruitment",
            "location": "Remote Americas / Global",
            "url": "https://distantjob.com/apply/principal-ai-solutions-consultant/",
            "description": (
                "Full-time remote placement for a trilingual (EN/FR/ES) Senior Cloud & AI Solutions Consultant "
                "with deep Azure, M365, Entra ID, MSP automation (Liongard, IT Glue), and Python/LLM architecture experience. "
                "Note: DistantJob places full-time remote contractors (40 hrs/wk)."
            ),
            "tags": "azure, m365, entra id, liongard, it glue, python, trilingual",
            "published_at": today,
        },
        {
            "platform_id": "remoteok_api",
            "platform_name": "Remote OK API (SysAdmin/Cloud/Python)",
            "category": "Category 6: Curated Remote-First Job Boards",
            "track": "Track F: Curated Remote-First & WFA Job Boards",
            "contract_caveat": "fractional_or_fulltime",
            "title": "Junior IT Dispatch Assistant",
            "company": "Reactive Ticket Corp",
            "location": "Global Remote",
            "url": "https://remoteok.com/",
            "description": (
                "Manage incoming email queue and basic account password resets across standard office tools."
            ),
            "tags": "entry level, ticket queue",
            "published_at": today,
        },
    ]
    return insert_opportunities(conn, samples, cfg, bypass_filter=True)


def run_scout(args: argparse.Namespace) -> None:
    cfg = load_config()
    conn = init_db()
    total_new = 0

    if getattr(args, "seed_verified", False) or getattr(args, "demo", False):
        seeded = seed_verified_baseline(conn, cfg)
        total_new += seeded
        print(f"[SCOUT] Seeded {seeded} verified multi-track baseline opportunities.")

    if getattr(args, "offline_only", False):
        print(f"[SCOUT] Offline run complete. Total new opportunities queued: {total_new}")
        conn.close()
        return

    platforms = [p for p in cfg.get("platforms", []) if p.get("enabled", True)]
    if getattr(args, "track", None):
        platforms = [p for p in platforms if args.track.lower() in p.get("track", "").lower()]
    if getattr(args, "platform", None):
        platforms = [
            p for p in platforms
            if args.platform.lower() in p.get("name", "").lower()
            or args.platform.lower() == p.get("id", "").lower()
        ]

    # 1. JSON APIs & RSS Feeds
    direct_feeds = [
        p for p in platforms
        if (p.get("type") or p.get("connector_type")) in ("json_api", "rss_feed")
    ]
    for p in direct_feeds:
        ptype = p.get("type") or p.get("connector_type")
        try:
            items = fetch_json_api(p) if ptype == "json_api" else fetch_rss_feed(p)
            added = insert_opportunities(conn, items, cfg)
            total_new += added
            print(f"[SCOUT] {ptype.upper()} | {p['name']}: fetched {len(items)}, {added} passed filter.")
        except Exception as exc:
            print(f"[SCOUT WARN] {p['name']} ({ptype}) unreachable or timed out: {exc}")

    # 2. Portal Dorks (Clustered by default to avoid HTTP 429 across 58+ portals)
    dork_platforms = [
        p for p in platforms
        if (p.get("type") or p.get("connector_type")) == "portal_dork"
    ]
    mode = getattr(args, "mode", "clustered")
    if dork_platforms:
        if mode == "clustered" and len(dork_platforms) > 4:
            print(f"[SCOUT] Running clustered portal dorks across {len(dork_platforms)} walled portals...")
            dork_items = fetch_clustered_portal_dorks(dork_platforms)
            added = insert_opportunities(conn, dork_items, cfg)
            total_new += added
            print(f"[SCOUT] Clustered Dorks: fetched {len(dork_items)}, {added} passed filter.")
        else:
            for p in dork_platforms:
                try:
                    items = fetch_portal_dork(p)
                    added = insert_opportunities(conn, items, cfg)
                    total_new += added
                    print(f"[SCOUT] DORK | {p['name']}: fetched {len(items)}, {added} passed filter.")
                    time.sleep(1.0)
                except Exception as exc:
                    print(f"[SCOUT WARN] {p['name']} dork failed: {exc}")

    print(f"[SCOUT] Pipeline complete. {total_new} new opportunities inserted into career_ops.db.")
    conn.close()


def cli_list_platforms() -> None:
    cfg = load_config()
    platforms = cfg.get("platforms", [])
    print(
        f"Total Registered Platforms: {len(platforms)} "
        f"(Version {cfg.get('version')})"
    )
    by_track = {}
    for p in platforms:
        by_track.setdefault(p.get("track", "Uncategorized"), []).append(p)
    for track, plist in sorted(by_track.items()):
        print(f"\n=== {track} ({len(plist)} platforms) ===")
        for p in plist:
            status = "ON " if p.get("enabled", True) else "OFF"
            ptype = p.get("type") or p.get("connector_type", "portal_dork")
            print(f"  [{status}] {p['id']:28s} | {ptype:11s} | {p['name']} ({p['url']})")


def cli_add_platform(args: argparse.Namespace) -> None:
    cfg = load_config()
    pid = re.sub(r"[^a-z0-9_]+", "_", args.name.lower()).strip("_")
    parsed_domain = urllib.parse.urlparse(args.url).netloc.replace("www.", "")
    notes_val = args.notes or getattr(args, "positioning", "") or "Added via SCOUT CLI."
    new_entry = {
        "id": pid,
        "name": args.name,
        "category": args.category or "Custom Added Platform",
        "track": args.track or "Track B: Async AI Evaluation & RLHF",
        "type": args.type,
        "enabled": True,
        "domain": parsed_domain,
        "url": args.url,
        "search_query": args.query or f'site:{parsed_domain} ("Azure" OR "M365" OR "Python" OR "French" OR "Spanish")',
        "contract_caveat": args.caveat or "fractional_or_fulltime",
        "notes": notes_val,
    }
    cfg.setdefault("platforms", []).append(new_entry)
    save_config(cfg)
    print(f"[SCOUT] Added platform '{args.name}' ({pid}) to platforms_config.json.")


def cli_add_keyword(args: argparse.Namespace) -> None:
    cfg = load_config()
    key = "hard_exclude_keywords" if args.exclude else "must_match_any_keyword"
    kw = args.keyword.lower().strip()
    target_list = cfg.setdefault("global_parameters", {}).setdefault(key, [])
    if kw not in target_list:
        target_list.append(kw)
        save_config(cfg)
        print(f"[SCOUT] Added '{kw}' to global_parameters.{key}.")
    else:
        print(f"[SCOUT] '{kw}' already exists in global_parameters.{key}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SCOUT Agent v4.0.0 — Multi-Track Opportunity Aggregator")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run", help="Execute daily SCOUT ingestion pipeline")
    run_p.add_argument("--mode", choices=["clustered", "individual"], default="clustered")
    run_p.add_argument("--track", help="Filter run to a specific Track substring")
    run_p.add_argument("--platform", help="Filter run to a specific Platform name or ID")
    run_p.add_argument("--seed-verified", action="store_true", help="Seed verified multi-track baseline leads")
    run_p.add_argument("--demo", action="store_true", help="Alias for --seed-verified (offline demo/validation)")
    run_p.add_argument("--offline-only", action="store_true", help="Skip live HTTP calls (seed only)")

    sub.add_parser("list-platforms", help="List all 73+ registered platforms by Track")
    sub.add_parser("list", help="Alias for list-platforms")
    sub.add_parser("seed-verified", help="Seed verified 6-track baseline leads into career_ops.db")

    add_p = sub.add_parser("add-platform", help="Register a new platform in platforms_config.json")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--type", choices=["portal_dork", "rss_feed", "json_api", "html_board"], required=True)
    add_p.add_argument("--url", required=True)
    add_p.add_argument("--query", default="")
    add_p.add_argument("--track", default="Track B: Async AI Evaluation & RLHF")
    add_p.add_argument("--category", default="Custom Added Platform")
    add_p.add_argument("--caveat", default="fractional_or_fulltime")
    add_p.add_argument("--notes", default="")
    add_p.add_argument("--positioning", default="")

    kw_p = sub.add_parser("add-keyword", help="Add a must-match or hard-exclude keyword")
    kw_p.add_argument("keyword")
    kw_p.add_argument("--exclude", action="store_true")

    return parser


if __name__ == "__main__":
    parser = build_parser()
    parsed_args = parser.parse_args()
    if parsed_args.command in ("list-platforms", "list"):
        cli_list_platforms()
    elif parsed_args.command == "add-platform":
        cli_add_platform(parsed_args)
    elif parsed_args.command == "add-keyword":
        cli_add_keyword(parsed_args)
    elif parsed_args.command == "seed-verified":
        cfg_obj = load_config()
        conn_obj = init_db()
        seeded_cnt = seed_verified_baseline(conn_obj, cfg_obj)
        conn_obj.close()
        print(f"[SCOUT] Seeded {seeded_cnt} verified multi-track baseline opportunities.")
    else:
        if not getattr(parsed_args, "command", None):
            parsed_args = parser.parse_args(["run"])
        run_scout(parsed_args)

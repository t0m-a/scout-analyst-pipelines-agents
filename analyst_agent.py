#!/usr/bin/env python3
"""
ANALYST Agent v4.0.0 — 6-Track Qualification, Trilingual Proposal Engine & Nginx Publisher
Dependencies: Python 3.10+ Standard Library ONLY

Evaluates every unscored row in `career_ops.db` using `master_profile.json` across 4 axes (0-100):
  1. Technical & Domain Fit (Max 40 pts) — Evaluates core technologies, systems engineering,
     cloud administration, scripting, documentation, and architecture skills.
  2. Role Scope & Flexibility (Max 20 pts) — Evaluates asynchronous flexibility, fractional
     scheduling, part-time hours, and self-paced workflows.
  3. Geographic & Language Alignment (Max 20 pts) — Evaluates remote eligibility, time zone
     alignment, and multilingual capabilities (English, French, Spanish).
  4. Contract & Engagement Structure (Max 20 pts) — Evaluates contractor, fractional, or advisory
     structures, and applies placement agency caveats where applicable.

Outputs:
  - `morning_brief.md`   : Daily executive briefing grouped by Verdict & Strategic Track.
  - `proposals_ready.md` : Ready-to-send English, French, and Spanish proposals + Executive Advisory Pitch.
  - `index.html`         : Unified single-page interactive HTML5/CSS3/JS dashboard.
"""

import argparse
import datetime
import html
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "master_profile.json"
CONFIG_PATH = BASE_DIR / "platforms_config.json"
DB_PATH = BASE_DIR / "career_ops.db"
BRIEF_PATH = BASE_DIR / "morning_brief.md"
PROPOSALS_PATH = BASE_DIR / "proposals_ready.md"
INDEX_HTML_PATH = BASE_DIR / "index.html"
PUBLIC_TUNNEL_URL = os.environ.get("PUBLIC_PORTAL_URL", "https://portal.example.com")
DEFAULT_NGINX_DIR = "/var/www/html"

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


def resolve_nginx_web_dir(custom_dir: Optional[str] = None) -> Optional[str]:
    candidates = []
    if custom_dir:
        candidates.append(custom_dir)
    if os.environ.get("NGINX_HTML_DIR"):
        candidates.append(os.environ["NGINX_HTML_DIR"])
    candidates.extend([
        DEFAULT_NGINX_DIR,
        str(BASE_DIR.parent.parent / "var" / "www" / "html"),
    ])
    for path in candidates:
        if path and os.path.isdir(path):
            return os.path.normpath(path)
    return None


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_db_schema(conn: sqlite3.Connection) -> None:
    existing_cols = {
        r[1] for r in conn.execute("PRAGMA table_info(opportunities)").fetchall()
    }
    for col_name, col_def in REQUIRED_COLUMNS.items():
        if col_name not in existing_cols and col_name != "id":
            conn.execute(f"ALTER TABLE opportunities ADD COLUMN {col_name} {col_def}")
    conn.commit()


def evaluate_opportunity(row: Dict[str, Any], profile: dict) -> dict:
    rubric = profile["scoring_rubric"]
    tech_weights = rubric.get("high_value_tech_keywords", {})
    gap_penalties = rubric.get("unlearned_gap_penalties", {})
    pos_flexibility = rubric.get("role_flexibility_signals", {})
    geo_signals = rubric.get("geo_language_signals", {})

    title = str(row.get("title") or "")
    company = str(row.get("company") or "")
    desc = str(row.get("description") or "")
    tags = str(row.get("tags") or "")
    loc = str(row.get("location") or "")
    track = str(row.get("track") or "")
    caveat = str(row.get("contract_caveat") or "fractional_or_fulltime")

    blob = f"{title} {company} {desc} {tags} {loc}".lower()

    # -------------------------------------------------------------------------
    # 1. Technical & Domain Fit (Max 40 pts)
    # -------------------------------------------------------------------------
    matched_skills = []
    raw_tech = 0
    for kw, weight in tech_weights.items():
        pattern = r"\b" + re.escape(kw.lower()) + r"\b"
        if re.search(pattern, blob):
            matched_skills.append(kw)
            raw_tech += weight

    tech_scaled = min(40, round((raw_tech / 34.0) * 40))

    if caveat == "micro_advisory":
        tech_scaled = max(tech_scaled, 36)

    gap_notes = []
    for gap_kw, pen in gap_penalties.items():
        pattern = r"\b" + re.escape(gap_kw.lower()) + r"\b"
        if re.search(pattern, blob):
            tech_scaled = max(0, tech_scaled + pen)
            gap_notes.append(f"{gap_kw} ({pen})")

    # -------------------------------------------------------------------------
    # 2. Role Scope & Flexibility (Max 20 pts)
    # -------------------------------------------------------------------------
    role_score = 12
    if caveat in ("async_flexible", "micro_advisory"):
        role_score = 18
    elif caveat == "fractional_friendly":
        role_score = 15

    for pos_kw, bonus in pos_flexibility.items():
        if pos_kw.lower() in blob:
            role_score += bonus
    role_score = min(20, role_score)

    # -------------------------------------------------------------------------
    # 3. Geographic & Language Alignment (Max 20 pts)
    # -------------------------------------------------------------------------
    geo_lang_score = 8
    if any(g in blob for g in geo_signals.get("geo_keywords", [])):
        geo_lang_score += 5
    if any(fr in blob for fr in geo_signals.get("french_keywords", [])) or "Track D" in track:
        geo_lang_score += 6
        if "français" not in matched_skills and "french" not in matched_skills:
            matched_skills.append("french")
    if any(es in blob for es in geo_signals.get("spanish_keywords", [])):
        geo_lang_score += 5
        if "spanish" not in matched_skills:
            matched_skills.append("spanish")
    geo_lang_score = min(20, geo_lang_score)

    # -------------------------------------------------------------------------
    # 4. Contract & Engagement Structure (Max 20 pts)
    # -------------------------------------------------------------------------
    contract_score = 12
    notes_list = []

    if caveat == "micro_advisory":
        contract_score = 20
        notes_list.append("Executive advisory / consultation scope.")
    elif caveat == "async_flexible":
        contract_score = 19
        notes_list.append("Self-paced asynchronous workflow.")
    elif caveat == "fractional_friendly":
        contract_score = 18
        notes_list.append("Fractional / part-time / deliverable friendly.")

    if any(k in blob for k in ("fractional", "part-time", "20 hours", "20h", "4 day week", "async", "freelance", "contract")):
        contract_score = min(20, contract_score + 4)

    if caveat == "full_time_only" or ("full-time" in blob and "fractional" not in blob and "part-time" not in blob):
        if caveat == "full_time_only":
            contract_score = max(4, contract_score - 6)
            notes_list.append("⚠️ FULL-TIME AGENCY CAVEAT (-6 pts): Agency primarily places 40h/wk full-time roles.")

    if gap_notes:
        notes_list.append("Skill gaps penalized: " + ", ".join(gap_notes))

    total_score = tech_scaled + role_score + geo_lang_score + contract_score

    # Verdict determination
    is_strictly_fulltime_agency = (
        caveat == "full_time_only"
        and "fractional" not in blob
        and "part-time" not in blob
        and "20 hours" not in blob
    )
    if is_strictly_fulltime_agency:
        total_score = min(total_score, 78)
        verdict = "POSSIBLE" if total_score >= rubric["verdict_thresholds"]["POSSIBLE"] else "SKIP"
    elif total_score >= rubric["verdict_thresholds"]["APPLY"]:
        verdict = "APPLY"
    elif total_score >= rubric["verdict_thresholds"]["POSSIBLE"]:
        verdict = "POSSIBLE"
    else:
        verdict = "SKIP"

    missing_str = ", ".join(gap_notes) if gap_notes else "None"
    return {
        "verdict": verdict,
        "total_score": int(total_score),
        "tech_score": int(tech_scaled),
        "safety_score": int(role_score),
        "geo_lang_score": int(geo_lang_score),
        "contract_score": int(contract_score),
        "matched_skills": ", ".join(matched_skills[:12]) if matched_skills else "general systems/cloud",
        "missing_gaps": missing_str,
        "red_flags": "",
        "analyst_notes": " | ".join(notes_list) if notes_list else "Standard alignment.",
    }


def build_proposal_bundle(row: Dict[str, Any], profile: dict) -> Tuple[str, str, str, str, str]:
    """
    Returns (proposal_en, proposal_fr, proposal_es, proposal_advisory, markdown_block)
    grounded in candidate preferences from master_profile.json.
    """
    cand = profile.get("candidate", {})
    cand_name = cand.get("name", "Candidate")
    cand_title = cand.get("title", "Senior Cloud & Systems Engineer")
    cand_loc = cand.get("location", "Remote")
    cand_portfolio = cand.get("portfolio", "https://portfolio.example.com")
    cand_linkedin = cand.get("linkedin", "https://linkedin.com/in/example")
    cand_email = cand.get("email", "contact@example.com")
    cand_phone = cand.get("phone", "+1-555-019-2834")
    cand_metrics = cand.get("verified_metrics", {})
    cand_years = cand_metrics.get("years_it_experience", "10+ years")
    cand_scale = cand_metrics.get("msp_scale", "multi-client environments")
    cand_reduction = cand_metrics.get("incident_reduction", "proactive incident reduction")
    cand_bcdr = cand_metrics.get("bcdr_reliability", "99%+ verification compliance")
    cand_tax = cand.get("tax_status", "Independent Contractor")

    title = row.get("title") or ""
    company = row.get("company") or ""
    track = row.get("track") or ""
    caveat = row.get("contract_caveat") or ""
    skills = row.get("matched_skills") or "Microsoft 365, Azure, Entra ID, Automation, Python"
    url = row.get("url") or ""

    pitch_en = (
        f"Hello {company} team,\n\n"
        f"Regarding the **{title}** opportunity: I bring {cand_years} of senior IT infrastructure, cloud administration, "
        f"and systems engineering experience ({cand_scale}). My core focus is systemic logic and proactive automation—delivering "
        f"{cand_reduction} using {skills}.\n\n"
        f"Operating as an independent contractor ({cand_loc}, {cand_tax}) and fluent in English, French, and Spanish, I deliver "
        f"high-accountability, well-documented asynchronous execution. You can review my architecture case studies at "
        f"{cand_portfolio}. Let's schedule a brief technical call this week to align on your immediate milestones.\n\n"
        f"Best regards,\n"
        f"{cand_name} | {cand_portfolio} | {cand_linkedin}"
    )

    pitch_fr = (
        f"Bonjour l'équipe {company},\n\n"
        f"Suite à votre publication pour la mission **{title}**, je vous propose mon expertise en Ingénierie Systèmes, "
        f"Cloud & Infrastructure ({cand_years} d'expérience sur des environnements critiques).\n\n"
        f"J'accompagne les organisations à distance ({cand_loc}) sur l'administration et la sécurisation des environnements "
        f"cloud, l'automatisation, et la standardisation documentaire ({skills})—avec {cand_reduction}.\n\n"
        f"Trilingue (français, anglais, espagnol), mon portfolio technique est consultable sur "
        f"{cand_portfolio}. Disponible pour échanger cette semaine sur vos objectifs.\n\n"
        f"Cordialement,\n"
        f"{cand_name} | {cand_portfolio} | {cand_email}"
    )

    pitch_es = (
        f"Hola equipo de {company},\n\n"
        f"En relación con la posición **{title}**: cuento con {cand_years} de experiencia como Consultor Senior de TI, "
        f"Ingeniero Cloud y Especialista en Sistemas gestionando entornos empresariales de forma remota ({cand_loc}).\n\n"
        f"Me especializo en auditoría lógica de sistemas, automatización y estandarización operativa ({skills}), "
        f"logrando {cand_reduction} y manteniendo {cand_bcdr}. Opero como contratista independiente ({cand_tax}) "
        f"trilingüe (inglés, francés, español). Pueden revisar mi portafolio en {cand_portfolio}. Quedo atento para coordinar una breve conversación técnica.\n\n"
        f"Atentamente,\n"
        f"{cand_name} | {cand_portfolio} | {cand_email}"
    )

    pitch_advisory = ""
    if caveat == "micro_advisory" or "Track E" in track:
        pitch_advisory = (
            "🎙️ 60-Second Executive Advisory Opening Pitch & Screening Note (EN):\n"
            f"Hello, I am {cand_name}, a {cand_title} with {cand_years} of enterprise infrastructure and systems "
            f"experience ({cand_scale}). I have hands-on operational, deployment, and vendor evaluation experience "
            "across modern EDR/ITDR/SIEM, BCDR, and cloud management platforms. Are we focusing today's consultation "
            "primarily on operational workflows and incident reduction, or top-down vendor consolidation and pricing tiers?\n\n"
            "📊 Instant Vendor Scorecard Reference (For Live Call):\n"
            "• Huntress (Managed EDR + ITDR + SIEM — 10/10): Strong channel ROI, human-verified SOC remediation cards, low false positives.\n"
            "• Acronis Cyber Protect Cloud (9/10 Unified / 7/10 Standalone): High efficiency when consolidating immutable BCDR, RMM, patching, and EDR into a single agent.\n"
            "• Blackpoint Cyber (CompassOne Standard w/ LogIC SIEM): Active host/identity isolation and extended compliance retention.\n"
            "• SaaS Alerts & Augmentt: Posture checks and SaaS monitoring requiring active operational tuning."
        )

    block = [
        f"## 🎯 [{row['verdict']} — {row['total_score']}/100] {title}",
        f"- **Company / Platform:** {company} (`{row['platform_name']}`)",
        f"- **Strategic Track:** {track}",
        f"- **Matched Stack:** `{skills}`",
        f"- **Direct Link:** {url}",
    ]
    if row.get("analyst_notes"):
        block.append(f"- **Analyst Notes:** {row['analyst_notes']}")
    block.append("")

    if pitch_advisory:
        block.extend(
            [
                "### 🎙️ 60-Second Executive Advisory Opening Pitch & Screening Note (EN)",
                pitch_advisory,
                "",
                "### 📊 Instant Vendor Scorecard Reference (For Live Call)",
                "- **Huntress (Managed EDR + ITDR + SIEM — 10/10):** Strong channel ROI, human-verified SOC remediation cards, low false positives.",
                "- **Acronis Cyber Protect Cloud (9/10 Unified / 7/10 Standalone):** High efficiency when consolidating immutable BCDR, RMM, patching, and EDR into a single agent.",
                "- **Blackpoint Cyber (CompassOne Standard w/ LogIC SIEM):** Active host/identity isolation and extended compliance retention.",
                "- **SaaS Alerts & Augmentt:** Posture checks and SaaS monitoring requiring active operational tuning.",
                "",
            ]
        )

    block.extend(
        [
            "### 🇬🇧 English Proposal / Outreach (Ready to Copy)",
            pitch_en,
            "",
            "### 🇫🇷 Proposition Commerciale / Message (Français)",
            pitch_fr,
            "",
            "### 🇪🇸 Propuesta Técnica / Mensaje (Español)",
            pitch_es,
            "",
            "---",
            "",
        ]
    )
    return pitch_en, pitch_fr, pitch_es, pitch_advisory, "\n".join(block)


def generate_trilingual_proposals(row: Dict[str, Any], profile: dict) -> str:
    _, _, _, _, md_block = build_proposal_bundle(row, profile)
    return md_block


SHARED_WEB_STYLES = """
  :root {
    --bg-page: #fafafa;
    --bg-card: #ffffff;
    --text-main: #2c2e33;
    --text-muted: #5a5d64;
    --accent-blue: #0084b8;
    --accent-cyan: #1badd6;
    --apply-bg: #ecfdf5;
    --apply-border: #10b981;
    --apply-text: #065f46;
    --possible-bg: #fffbeb;
    --possible-border: #f59e0b;
    --possible-text: #92400e;
    --skip-bg: #f3f4f6;
    --skip-border: #9ca3af;
    --skip-text: #4b5563;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0;
    padding: 0;
    color: var(--text-main);
    background-color: var(--bg-page);
    font-family: "Helvetica Neue", Helvetica, "Open Sans", Arial, sans-serif;
    line-height: 1.55;
  }
  #navbar {
    position: fixed;
    top: 0;
    left: 0;
    width: 300px;
    height: 100%;
    border-right: 1px solid rgba(19, 27, 27, 0.25);
    background: #fafafa;
    z-index: 900;
    display: flex;
    flex-direction: column;
    transition: transform 0.25s ease, width 0.25s ease;
  }
  .navbar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 12px 10px 16px;
    border-bottom: 1px solid rgba(77, 78, 83, 0.15);
  }
  .header-title {
    color: #2c2e33;
    margin: 0;
    font-size: 1.18em;
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sidebar-fold-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 1px solid rgba(77, 78, 83, 0.25);
    border-radius: 6px;
    background: #ffffff;
    color: #2c2e33;
    font-size: 1.05em;
    font-weight: 700;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
  }
  .sidebar-fold-btn:hover {
    background: var(--accent-blue);
    color: #ffffff;
    border-color: var(--accent-blue);
  }
  #sidebar-unfold-btn {
    position: fixed;
    top: 14px;
    left: 14px;
    z-index: 950;
    display: none;
    align-items: center;
    gap: 6px;
    padding: 8px 12px;
    border: 1px solid rgba(19, 27, 27, 0.25);
    border-radius: 6px;
    background: #ffffff;
    color: #2c2e33;
    font-size: 0.88em;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
  }
  #sidebar-unfold-btn:hover {
    background: var(--accent-blue);
    color: #ffffff;
    border-color: var(--accent-blue);
  }
  body.sidebar-collapsed #navbar {
    transform: translateX(-300px);
  }
  body.sidebar-collapsed #sidebar-unfold-btn {
    display: inline-flex;
  }
  .hamburger-btn { display: none; }
  #navbar ul {
    flex: 1;
    margin: 0;
    padding: 0;
    overflow-y: auto;
    list-style: none;
  }
  #navbar li {
    border-top: 1px solid rgba(77, 78, 83, 0.2);
  }
  #navbar li.nav-group-header {
    background: #f1f5f9;
    padding: 7px 14px;
    font-size: 0.76em;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #475569;
    cursor: pointer;
    user-select: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  #navbar li.nav-group-header:hover {
    background: #e2e8f0;
    color: #0f172a;
  }
  .nav-group-chevron {
    display: inline-block;
    transition: transform 0.2s ease;
    font-size: 0.95em;
  }
  #navbar li.nav-group-header.folded .nav-group-chevron {
    transform: rotate(-90deg);
  }
  #navbar li.nav-group-item.folded-item {
    display: none;
  }
  #navbar a {
    display: block;
    padding: 9px 18px;
    color: #3d3e43;
    text-decoration: none;
    font-size: 0.9em;
    transition: background 0.15s ease, color 0.15s ease;
  }
  #navbar a:hover, #navbar a.active-nav {
    background: linear-gradient(-90deg, #70c1d8 0%, #1badd6 100%);
    color: #fff !important;
    font-weight: 600;
  }
  #main-doc {
    margin-left: 300px;
    padding: 28px 36px 60px 36px;
    max-width: 1240px;
    transition: margin-left 0.25s ease, max-width 0.25s ease;
  }
  body.sidebar-collapsed #main-doc {
    margin-left: 0;
    max-width: 1440px;
    padding-left: 64px;
  }
  .top-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    color: #ffffff;
    padding: 24px 28px;
    border-radius: 10px;
    margin-bottom: 22px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08);
  }
  .top-banner h1 {
    margin: 0 0 8px 0;
    font-size: 1.62em;
    font-weight: 600;
    color: #ffffff;
  }
  .top-banner p {
    margin: 4px 0;
    color: #cbd5e1;
    font-size: 0.94em;
  }
  .banner-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 12px;
  }
  .banner-pill {
    background: rgba(255, 255, 255, 0.12);
    border: 1px solid rgba(255, 255, 255, 0.22);
    color: #f8fafc;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.8em;
    font-weight: 600;
  }
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
    gap: 14px;
    margin-bottom: 22px;
  }
  .kpi-card {
    background: var(--bg-card);
    border-radius: 8px;
    padding: 16px 18px;
    border-left: 5px solid var(--accent-blue);
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    cursor: pointer;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  .kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  }
  .kpi-card.apply { border-left-color: var(--apply-border); }
  .kpi-card.possible { border-left-color: var(--possible-border); }
  .kpi-card.skip { border-left-color: var(--skip-border); }
  .kpi-value {
    font-size: 1.7em;
    font-weight: 700;
    line-height: 1.1;
  }
  .kpi-label {
    font-size: 0.84em;
    color: var(--text-muted);
    margin-top: 4px;
  }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
    justify-content: space-between;
    background: var(--bg-card);
    padding: 12px 16px;
    border-radius: 8px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    margin-bottom: 20px;
  }
  .filter-group {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .btn-tab {
    border: 1px solid #d1d5db;
    background: #f9fafb;
    color: #374151;
    padding: 7px 13px;
    border-radius: 6px;
    font-size: 0.86em;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    transition: all 0.15s ease;
  }
  .btn-tab:hover, .btn-tab.active {
    background: var(--accent-blue);
    color: #ffffff !important;
    border-color: var(--accent-blue);
  }
  .track-select {
    padding: 7px 11px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    background: #ffffff;
    color: #1f2937;
    font-size: 0.86em;
    font-weight: 600;
    cursor: pointer;
  }
  .search-box {
    padding: 8px 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    min-width: 220px;
    font-size: 0.88em;
  }
  .opp-card {
    background: var(--bg-card);
    border: 1px solid #e5e7eb;
    border-left: 5px solid var(--accent-blue);
    border-radius: 8px;
    padding: 18px 22px;
    margin-bottom: 16px;
    box-shadow: 0 2px 5px rgba(0,0,0,0.04);
  }
  .opp-card.verdict-APPLY { border-left-color: var(--apply-border); }
  .opp-card.verdict-POSSIBLE { border-left-color: var(--possible-border); }
  .opp-card.verdict-SKIP { border-left-color: var(--skip-border); opacity: 0.86; }
  .opp-header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
    margin-bottom: 10px;
  }
  .opp-title {
    margin: 0;
    font-size: 1.15em;
    font-weight: 600;
    color: #111827;
  }
  .badge {
    display: inline-block;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.8em;
    font-weight: 700;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }
  .badge-APPLY { background: var(--apply-bg); color: var(--apply-text); border: 1px solid var(--apply-border); }
  .badge-POSSIBLE { background: var(--possible-bg); color: var(--possible-text); border: 1px solid var(--possible-border); }
  .badge-SKIP { background: var(--skip-bg); color: var(--skip-text); border: 1px solid var(--skip-border); }
  .meta-line {
    font-size: 0.88em;
    color: var(--text-muted);
    margin-bottom: 10px;
  }
  .caveat-pill {
    display: inline-block;
    background: #eef2ff;
    color: #3730a3;
    border: 1px solid #c7d2fe;
    padding: 1px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    font-weight: 600;
  }
  .caveat-pill.full_time_only {
    background: #fffbeb;
    color: #92400e;
    border-color: #fde68a;
  }
  .caveat-pill.micro_advisory {
    background: #f0fdf4;
    color: #166534;
    border-color: #bbf7d0;
  }
  .score-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 10px;
  }
  .score-pill {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 5px;
    padding: 3px 9px;
    font-size: 0.82em;
    font-weight: 600;
    color: #334155;
  }
  .skill-tag {
    display: inline-block;
    background: #e0f2fe;
    color: #0369a1;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    margin: 2px 4px 2px 0;
    font-family: monospace;
  }
  .gap-tag {
    display: inline-block;
    background: #fef2f2;
    color: #b91c1c;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.8em;
    margin: 2px 4px 2px 0;
    font-family: monospace;
  }
  .card-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 12px;
  }
  .btn-action {
    display: inline-block;
    padding: 6px 14px;
    border-radius: 5px;
    font-size: 0.86em;
    font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    border: 1px solid transparent;
  }
  .btn-primary {
    background: linear-gradient(90deg, #0084b8, #1badd6);
    color: #ffffff !important;
  }
  .btn-secondary {
    background: #f8fafc;
    color: #0f172a !important;
    border-color: #cbd5e1;
  }
  .btn-secondary:hover {
    background: #e2e8f0;
  }
  .proposal-box {
    background: #0f172a;
    color: #f8fafc;
    padding: 16px;
    border-radius: 6px;
    font-family: Consolas, Monaco, "Courier New", monospace;
    font-size: 0.88em;
    white-space: pre-wrap;
    word-break: break-word;
    line-height: 1.5;
    margin: 8px 0 0 0;
    position: relative;
  }
  .lang-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    align-items: center;
    margin-top: 10px;
  }
  .guardrail-list li {
    margin-bottom: 8px;
  }
  .raw-md-drawer {
    display: none;
    margin-top: 20px;
  }
  .raw-md-drawer.open {
    display: block;
  }
  .radar-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 14px;
    margin-top: 14px;
  }
  .radar-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 4px solid var(--accent-blue);
    border-radius: 6px;
    padding: 14px 16px;
  }
  .radar-box h4 {
    margin: 0 0 6px 0;
    color: #0f172a;
    font-size: 0.96em;
  }
  .radar-box p {
    margin: 0;
    font-size: 0.85em;
    color: #475569;
  }
  footer {
    margin-top: 40px;
    padding-top: 14px;
    border-top: 1px solid #d1d5db;
    text-align: center;
    font-size: 0.82em;
    color: var(--text-muted);
  }
  @media only screen and (max-width: 800px) {
    #navbar, body.sidebar-collapsed #navbar {
      width: 100%;
      height: auto;
      position: fixed;
      transform: none;
      border-right: none;
      border-bottom: 1px solid rgba(77,78,83,0.25);
      background: rgba(250, 250, 250, 0.95);
      backdrop-filter: blur(10px);
    }
    .navbar-header {
      padding: 0;
      border-bottom: none;
    }
    .header-title {
      text-align: left;
      margin: 0;
      padding: 12px 60px 12px 16px;
      font-size: 1.15em;
    }
    .sidebar-fold-btn, #sidebar-unfold-btn, body.sidebar-collapsed #sidebar-unfold-btn {
      display: none !important;
    }
    .hamburger-btn {
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      gap: 5px;
      position: absolute;
      top: 8px;
      right: 14px;
      width: 38px;
      height: 38px;
      border: 1px solid rgba(77,78,83,0.25);
      border-radius: 6px;
      background: #fff;
      cursor: pointer;
    }
    .hamburger-line {
      display: block;
      width: 20px;
      height: 2px;
      background: #1f2023;
    }
    #navbar ul { display: none; max-height: 70vh; }
    #navbar.nav-open ul { display: block; }
    #main-doc, body.sidebar-collapsed #main-doc {
      margin-left: 0;
      margin-top: 58px;
      padding: 16px;
    }
  }
"""


def extract_track_code(track_str: str) -> str:
    m = re.match(r"^(Track\s+[A-F])", str(track_str or "").strip(), re.IGNORECASE)
    return m.group(1).upper() if m else "OTHER"


def build_unified_index_html(
    today_str: str,
    updated_ts: str,
    apply_rows: List[Dict[str, Any]],
    possible_rows: List[Dict[str, Any]],
    skip_rows: List[Dict[str, Any]],
    brief_md: str,
    proposals_md: str,
    profile: dict,
    cfg: dict,
    public_url: str = PUBLIC_TUNNEL_URL,
) -> str:
    def render_skill_pills(skills_str: str, css_class: str = "skill-tag") -> str:
        if not skills_str or skills_str == "None":
            return '<span style="color:#6b7280;font-size:0.85em;">None</span>'
        parts = [s.strip() for s in skills_str.split(",") if s.strip()]
        return "".join(f'<span class="{css_class}">{html.escape(p)}</span>' for p in parts)

    total_platforms = len(cfg.get("platforms", []))
    actionable_rows = apply_rows + possible_rows
    brief_cards_html: List[str] = []
    proposal_cards_html: List[str] = []
    nav_apply_links: List[str] = []

    for idx, r in enumerate(apply_rows + possible_rows + skip_rows, 1):
        verdict = r.get("verdict") or "SKIP"
        jhash = r["job_hash"]
        track_raw = r.get("track") or "Track F: Curated Remote-First & WFA Job Boards"
        track_code = extract_track_code(track_raw)
        caveat_raw = r.get("contract_caveat") or "fractional_or_fulltime"

        title_esc = html.escape(str(r.get("title") or ""))
        comp_esc = html.escape(str(r.get("company") or ""))
        track_esc = html.escape(track_raw)
        plat_esc = html.escape(str(r.get("platform_name") or ""))
        loc_esc = html.escape(str(r.get("location") or ""))
        notes_esc = html.escape(str(r.get("analyst_notes") or ""))
        url_esc = html.escape(str(r.get("url") or "#"))
        caveat_esc = html.escape(caveat_raw)

        gaps_or_flags = r.get("red_flags") or r.get("missing_gaps") or "None"
        if gaps_or_flags == "":
            gaps_or_flags = "None"

        proposal_btn = ""
        inline_proposal_drawer = ""
        if verdict in ("APPLY", "POSSIBLE"):
            p_en = html.escape(r.get("proposal_en") or "")
            p_fr = html.escape(r.get("proposal_fr") or "")
            p_es = html.escape(r.get("proposal_es") or "")
            p_adv = html.escape(r.get("proposal_advisory") or "")

            adv_tab_btn = ""
            adv_pane_html = ""
            if p_adv:
                adv_tab_btn = (
                    f'<button type="button" class="btn-tab" '
                    f'onclick="switchLang(\'inline-{jhash}\', \'adv\', this)">🎙️ 60s Advisory &amp; Scorecard</button>'
                )
                adv_pane_html = f"""
              <div class="lang-pane lang-adv-inline-{jhash}" style="display:none;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
                  <strong>🎙️ 60-Second Executive Advisory Pitch &amp; MSSP Vendor Scorecard</strong>
                  <button type="button" class="btn-action btn-primary" onclick="copyText('inline-adv-{jhash}', this)">📋 Copy Advisory</button>
                </div>
                <pre id="inline-adv-{jhash}" class="proposal-box">{p_adv}</pre>
              </div>"""

            proposal_btn = (
                f'<button type="button" class="btn-action btn-primary" onclick="toggleInlineProposal(\'{jhash}\')">'
                f'✍️ Toggle EN/FR/ES Proposals</button>'
                f'<button type="button" class="btn-action btn-secondary" onclick="jumpToProposal(\'{jhash}\')">'
                f'📄 Open in Proposals View →</button>'
            )
            inline_proposal_drawer = f"""
            <div id="inline-prop-{jhash}" class="raw-md-drawer" style="margin-top:14px;border-top:1px dashed #cbd5e1;padding-top:12px;">
              <div class="lang-tabs">
                <button type="button" class="btn-tab active" onclick="switchLang('inline-{jhash}', 'en', this)">🇬🇧 English</button>
                <button type="button" class="btn-tab" onclick="switchLang('inline-{jhash}', 'fr', this)">🇫🇷 Français</button>
                <button type="button" class="btn-tab" onclick="switchLang('inline-{jhash}', 'es', this)">🇪🇸 Español</button>
                {adv_tab_btn}
                <button type="button" class="btn-tab" onclick="switchLang('inline-{jhash}', 'all', this)">🌐 Show All</button>
              </div>
              {adv_pane_html}
              <div class="lang-pane lang-en-inline-{jhash}">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
                  <strong>🇬🇧 English Proposal / Outreach</strong>
                  <button type="button" class="btn-action btn-primary" onclick="copyText('inline-en-{jhash}', this)">📋 Copy EN</button>
                </div>
                <pre id="inline-en-{jhash}" class="proposal-box">{p_en}</pre>
              </div>
              <div class="lang-pane lang-fr-inline-{jhash}" style="display:none;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
                  <strong>🇫🇷 Proposition Commerciale (Français)</strong>
                  <button type="button" class="btn-action btn-primary" onclick="copyText('inline-fr-{jhash}', this)">📋 Copier FR</button>
                </div>
                <pre id="inline-fr-{jhash}" class="proposal-box">{p_fr}</pre>
              </div>
              <div class="lang-pane lang-es-inline-{jhash}" style="display:none;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:10px;">
                  <strong>🇪🇸 Propuesta Técnica (Español)</strong>
                  <button type="button" class="btn-action btn-primary" onclick="copyText('inline-es-{jhash}', this)">📋 Copiar ES</button>
                </div>
                <pre id="inline-es-{jhash}" class="proposal-box">{p_es}</pre>
              </div>
            </div>
            """

        brief_cards_html.append(f"""
        <article class="opp-card brief-card verdict-{verdict}" data-verdict="{verdict}" data-track="{track_code}" id="brief-{jhash}">
          <div class="opp-header">
            <h3 class="opp-title">#{idx}. [{r['total_score']}/100] {title_esc} — <span style="font-weight:400;color:#4b5563;">{comp_esc}</span></h3>
            <span class="badge badge-{verdict}">{verdict} · {r['total_score']}/100</span>
          </div>
          <div class="meta-line">
            <strong>Track:</strong> {track_esc} &nbsp;|&nbsp;
            <strong>Platform:</strong> {plat_esc} &nbsp;|&nbsp;
            <strong>Location:</strong> {loc_esc} &nbsp;|&nbsp;
            <span class="caveat-pill {caveat_esc}">{caveat_esc}</span>
          </div>
          <div class="score-pills">
            <span class="score-pill">⚙️ Tech: {r['tech_score']}/40</span>
            <span class="score-pill">🛡️ Role Fit: {r['safety_score']}/20</span>
            <span class="score-pill">🌎 Geo / Language: {r['geo_lang_score']}/20</span>
            <span class="score-pill">⏱️ Contract Fit: {r['contract_score']}/20</span>
          </div>
          <div style="margin-bottom:6px;">
            <strong style="font-size:0.86em;">Matched Stack:</strong> {render_skill_pills(r.get('matched_skills') or '', 'skill-tag')}
            &nbsp;&nbsp;
            <strong style="font-size:0.86em;">Skill Gaps:</strong> {render_skill_pills(gaps_or_flags, 'gap-tag')}
          </div>
          <div style="font-size:0.92em;color:#374151;margin-top:6px;">
            <strong>Analyst Verdict &amp; Notes:</strong> {notes_esc}
          </div>
          <div class="card-actions">
            {proposal_btn}
            <a class="btn-action btn-secondary" href="{url_esc}" target="_blank" rel="noopener">🔗 Open Source Role / Link</a>
          </div>
          {inline_proposal_drawer}
        </article>
        """)

    for idx, r in enumerate(actionable_rows, 1):
        verdict = r.get("verdict") or "POSSIBLE"
        jhash = r["job_hash"]
        track_raw = r.get("track") or "Track F: Curated Remote-First & WFA Job Boards"
        track_code = extract_track_code(track_raw)
        title_esc = html.escape(str(r.get("title") or ""))
        comp_esc = html.escape(str(r.get("company") or ""))
        plat_esc = html.escape(str(r.get("platform_name") or ""))
        track_esc = html.escape(track_raw)
        url_esc = html.escape(str(r.get("url") or "#"))
        p_en = html.escape(r.get("proposal_en") or "")
        p_fr = html.escape(r.get("proposal_fr") or "")
        p_es = html.escape(r.get("proposal_es") or "")
        p_adv = html.escape(r.get("proposal_advisory") or "")

        icon = "🔥" if verdict == "APPLY" else "🟡"
        if idx <= 18:
            nav_apply_links.append(
                f'<li class="nav-group-item" data-group="matches"><a href="#brief-{jhash}" onclick="switchMainView(\'brief\')">{icon} [{r["total_score"]}] {comp_esc[:22]}</a></li>'
            )

        adv_tab_btn = ""
        adv_pane_html = ""
        if p_adv:
            adv_tab_btn = (
                f'<button type="button" class="btn-tab" '
                f'onclick="switchLang(\'{jhash}\', \'adv\', this)">🎙️ 60s Advisory &amp; Scorecard</button>'
            )
            adv_pane_html = f"""
          <div class="lang-pane lang-adv-{jhash}" style="display:none;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
              <strong>🎙️ 60-Second Executive Advisory Pitch &amp; MSSP Vendor Scorecard</strong>
              <button type="button" class="btn-action btn-primary" onclick="copyText('prop-adv-{jhash}', this)">📋 Copy Advisory Pitch</button>
            </div>
            <pre id="prop-adv-{jhash}" class="proposal-box">{p_adv}</pre>
          </div>"""

        proposal_cards_html.append(f"""
        <article class="opp-card prop-card verdict-{verdict}" data-verdict="{verdict}" data-track="{track_code}" id="job-{jhash}">
          <div class="opp-header">
            <h3 class="opp-title">#{idx}. [{verdict} — {r['total_score']}/100] {title_esc} ({comp_esc})</h3>
            <span class="badge badge-{verdict}">{verdict} · {r['total_score']}/100</span>
          </div>
          <div class="meta-line">
            <strong>Track:</strong> {track_esc} &nbsp;|&nbsp;
            <strong>Platform:</strong> {plat_esc} &nbsp;|&nbsp;
            <strong>Direct URL:</strong> <a href="{url_esc}" target="_blank" rel="noopener">{url_esc}</a>
            &nbsp;|&nbsp;
            <a href="#brief-{jhash}" onclick="switchMainView('brief')">🔍 Score Breakdown in Morning Brief</a>
          </div>

          <div class="lang-tabs">
            <button type="button" class="btn-tab active" onclick="switchLang('{jhash}', 'en', this)">🇬🇧 English</button>
            <button type="button" class="btn-tab" onclick="switchLang('{jhash}', 'fr', this)">🇫🇷 Français</button>
            <button type="button" class="btn-tab" onclick="switchLang('{jhash}', 'es', this)">🇪🇸 Español</button>
            {adv_tab_btn}
            <button type="button" class="btn-tab" onclick="switchLang('{jhash}', 'all', this)">🌐 Show All</button>
          </div>

          {adv_pane_html}

          <div class="lang-pane lang-en-{jhash}">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
              <strong>🇬🇧 English Proposal / Outreach (Ready to Copy)</strong>
              <button type="button" class="btn-action btn-primary" onclick="copyText('prop-en-{jhash}', this)">📋 Copy English Pitch</button>
            </div>
            <pre id="prop-en-{jhash}" class="proposal-box">{p_en}</pre>
          </div>

          <div class="lang-pane lang-fr-{jhash}" style="display:none;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
              <strong>🇫🇷 Proposition Commerciale (Français)</strong>
              <button type="button" class="btn-action btn-primary" onclick="copyText('prop-fr-{jhash}', this)">📋 Copier la proposition FR</button>
            </div>
            <pre id="prop-fr-{jhash}" class="proposal-box">{p_fr}</pre>
          </div>

          <div class="lang-pane lang-es-{jhash}" style="display:none;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;">
              <strong>🇪🇸 Propuesta Técnica (Español)</strong>
              <button type="button" class="btn-action btn-primary" onclick="copyText('prop-es-{jhash}', this)">📋 Copiar propuesta ES</button>
            </div>
            <pre id="prop-es-{jhash}" class="proposal-box">{p_es}</pre>
          </div>
        </article>
        """)

    scorecard_items_html = []
    for vendor, rating in profile.get("candidate", {}).get("mssp_vendor_scorecard", {}).items():
        scorecard_items_html.append(
            f'<div class="radar-box"><h4>🛡️ {html.escape(vendor)}</h4><p>{html.escape(rating)}</p></div>'
        )

    cand = profile.get("candidate", {})
    cand_name = html.escape(str(cand.get("name") or "Candidate"))
    cand_title = html.escape(str(cand.get("title") or "Senior Systems & Cloud Engineer"))
    cand_loc = html.escape(str(cand.get("location") or "Remote"))
    cand_portfolio = html.escape(str(cand.get("portfolio") or "https://portfolio.example.com"))
    cand_linkedin = html.escape(str(cand.get("linkedin") or "https://linkedin.com/in/example"))
    cand_tax = html.escape(str(cand.get("tax_status") or "Independent Contractor"))
    cand_metrics = cand.get("verified_metrics", {})
    cand_years = html.escape(str(cand_metrics.get("years_it_experience") or "10+ years"))

    total_count = len(apply_rows) + len(possible_rows) + len(skip_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Scout &amp; Analyst v4.0.0 Career Pipeline — {today_str}</title>
  <link rel="canonical" href="{public_url}/">
  <style>{SHARED_WEB_STYLES}</style>
</head>
<body>
  <button type="button" id="sidebar-unfold-btn" aria-label="Unfold navigation sidebar" title="Unfold sidebar ([)" onclick="toggleSidebar()">
    <span>☰</span> <span>Unfold Nav</span>
  </button>

  <nav id="navbar">
    <div class="navbar-header">
      <header class="header-title">Scout &amp; Analyst v4.0</header>
      <button type="button" class="sidebar-fold-btn" aria-label="Fold navigation sidebar" title="Fold sidebar ([)" onclick="toggleSidebar()">«</button>
    </div>
    <button type="button" class="hamburger-btn" aria-label="Toggle navigation" onclick="this.parentElement.classList.toggle('nav-open');">
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
      <span class="hamburger-line"></span>
    </button>
    <ul onclick="if(event.target.tagName==='A'){{this.parentElement.classList.remove('nav-open');}}">
      <li class="nav-group-header" data-group-toggle="views" onclick="toggleNavGroup('views', this)">
        <span>Dashboard Views</span>
        <span class="nav-group-chevron">▾</span>
      </li>
      <li class="nav-group-item" data-group="views"><a href="#morning-brief" id="nav-brief" class="active-nav" onclick="switchMainView('brief')">☕ Morning Brief ({total_count})</a></li>
      <li class="nav-group-item" data-group="views"><a href="#proposals-ready" id="nav-proposals" onclick="switchMainView('proposals')">✍️ Proposals Ready ({len(actionable_rows)})</a></li>
      <li class="nav-group-item" data-group="views"><a href="#radar-coverage" id="nav-radar" onclick="switchMainView('radar')">🗺️ 6-Track Radar ({total_platforms})</a></li>
      <li class="nav-group-item" data-group="views"><a href="#raw-markdown" id="nav-markdown" onclick="switchMainView('markdown')">📄 Raw Markdown (.md)</a></li>
      <li class="nav-group-item" data-group="views"><a href="#guardrails" onclick="switchMainView('brief')">🎯 Daily Execution Guardrails</a></li>

      <li class="nav-group-header" data-group-toggle="tracks" onclick="toggleNavGroup('tracks', this)">
        <span>6 Strategic Tracks</span>
        <span class="nav-group-chevron">▾</span>
      </li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('ALL');">🌐 All 6 Tracks ({total_count})</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK A');">🤝 Track A: Direct B2B &amp; MSP</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK B');">🤖 Track B: AI Eval &amp; RLHF</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK C');">🌎 Track C: LATAM &amp; Vetted</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK D');">🇫🇷 Track D: Francophone &amp; EU</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK E');">🎙️ Track E: Expert Advisory</a></li>
      <li class="nav-group-item" data-group="tracks"><a href="#morning-brief" onclick="switchMainView('brief'); filterByTrack('TRACK F');">📡 Track F: Remote Boards</a></li>

      <li class="nav-group-header" data-group-toggle="links" onclick="toggleNavGroup('links', this)">
        <span>External Links</span>
        <span class="nav-group-chevron">▾</span>
      </li>
      <li class="nav-group-item" data-group="links"><a href="{public_url}" target="_blank" rel="noopener">🌐 Live Portal</a></li>
      <li class="nav-group-item" data-group="links"><a href="{cand_portfolio}" target="_blank" rel="noopener">💼 Portfolio</a></li>
      <li class="nav-group-item" data-group="links"><a href="{cand_linkedin}" target="_blank" rel="noopener">🔗 LinkedIn</a></li>

      <li class="nav-group-header" data-group-toggle="matches" onclick="toggleNavGroup('matches', this)">
        <span>Top Matches ({len(nav_apply_links)})</span>
        <span class="nav-group-chevron">▾</span>
      </li>
      {"".join(nav_apply_links)}
    </ul>
  </nav>

  <main id="main-doc">
    <section class="top-banner">
      <h1>🎯 Scout &amp; Analyst Career Pipeline Portal ({today_str})</h1>
      <p>
        <strong>Engine Version:</strong> SCOUT + ANALYST v4.0.0 &nbsp;|&nbsp;
        <strong>Candidate:</strong> {cand_name} ({cand_title}) &nbsp;|&nbsp;
        <strong>Monitored Portals:</strong> {total_platforms} Active Platforms (6 Strategic Tracks A–F)
      </p>
      <p>
        <strong>Portal:</strong> <a href="{public_url}" style="color:#38bdf8;text-decoration:none;">{public_url}</a>
        &nbsp;|&nbsp; <strong>Last Synced:</strong> {updated_ts}
      </p>
      <div class="banner-pills">
        <span class="banner-pill">🌐 {cand_loc}</span>
        <span class="banner-pill">📄 {cand_tax}</span>
        <span class="banner-pill">💼 {cand_years}</span>
        <span class="banner-pill">🗣️ Multilingual (EN / FR / ES)</span>
      </div>
    </section>

    <section class="kpi-grid">
      <div class="kpi-card apply" onclick="switchMainView('brief'); filterCards('APPLY');">
        <div class="kpi-value" style="color:#059669;">🔥 {len(apply_rows)}</div>
        <div class="kpi-label"><strong>APPLY</strong> (Score ≥ 80/100)</div>
      </div>
      <div class="kpi-card possible" onclick="switchMainView('brief'); filterCards('POSSIBLE');">
        <div class="kpi-value" style="color:#d97706;">🟡 {len(possible_rows)}</div>
        <div class="kpi-label"><strong>POSSIBLE</strong> (Score 62–79/100)</div>
      </div>
      <div class="kpi-card skip" onclick="switchMainView('brief'); filterCards('SKIP');">
        <div class="kpi-value" style="color:#4b5563;">🛑 {len(skip_rows)}</div>
        <div class="kpi-label"><strong>SKIPPED</strong> (Filtered / Low Fit)</div>
      </div>
      <div class="kpi-card" onclick="switchMainView('proposals'); filterCards('ALL');">
        <div class="kpi-value" style="color:#0084b8;">✍️ {len(actionable_rows)}</div>
        <div class="kpi-label"><strong>Trilingual Proposals</strong> (EN / FR / ES)</div>
      </div>
      <div class="kpi-card" onclick="switchMainView('radar');">
        <div class="kpi-value" style="color:#0f172a;">🛰️ {total_platforms}</div>
        <div class="kpi-label"><strong>6-Track Radar</strong> (Active Portals)</div>
      </div>
    </section>

    <section class="toolbar">
      <div class="filter-group">
        <button type="button" class="btn-tab active" id="tab-view-brief" onclick="switchMainView('brief')">☕ Morning Brief ({total_count})</button>
        <button type="button" class="btn-tab" id="tab-view-proposals" onclick="switchMainView('proposals')">✍️ Proposals Ready ({len(actionable_rows)})</button>
        <button type="button" class="btn-tab" id="tab-view-radar" onclick="switchMainView('radar')">🗺️ 6-Track Radar &amp; Scorecard</button>
        <button type="button" class="btn-tab" id="tab-view-markdown" onclick="switchMainView('markdown')">📄 Raw Markdown Files</button>
      </div>
      <div class="filter-group" id="verdictFilterBar">
        <button type="button" class="btn-tab active" data-filter="ALL" onclick="filterCards('ALL')">All</button>
        <button type="button" class="btn-tab" data-filter="APPLY" onclick="filterCards('APPLY')">🔥 APPLY ({len(apply_rows)})</button>
        <button type="button" class="btn-tab" data-filter="POSSIBLE" onclick="filterCards('POSSIBLE')">🟡 POSSIBLE ({len(possible_rows)})</button>
        <button type="button" class="btn-tab" data-filter="SKIP" onclick="filterCards('SKIP')">🛑 SKIP ({len(skip_rows)})</button>
        <select id="trackFilterSelect" class="track-select" aria-label="Filter by Strategic Track" onchange="filterByTrack(this.value)">
          <option value="ALL">All 6 Strategic Tracks</option>
          <option value="TRACK A">Track A: Direct B2B &amp; Fractional MSP (6)</option>
          <option value="TRACK B">Track B: AI Training &amp; RLHF (20 Portals)</option>
          <option value="TRACK C">Track C: LATAM &amp; Vetted Networks (16)</option>
          <option value="TRACK D">Track D: Francophone &amp; EU Portals (9)</option>
          <option value="TRACK E">Track E: Executive Expert Networks (6)</option>
          <option value="TRACK F">Track F: Curated Remote Boards (16)</option>
        </select>
      </div>
      <input type="search" id="searchInput" class="search-box" placeholder="Filter by skill, company, track..." oninput="applyFilters()">
    </section>

    <!-- VIEW 1: MORNING BRIEF -->
    <section id="view-brief">
      <div id="briefCardsContainer">
        {"".join(brief_cards_html)}
      </div>

      <section id="guardrails" class="opp-card" style="border-left-color:#0084b8;margin-top:28px;">
        <h2 style="margin-top:0;">🎯 Daily Execution Workflow</h2>
        <ol class="guardrail-list">
          <li><strong>Review Morning Briefing:</strong> Inspect prioritized high-scoring opportunities in the <strong>☕ Morning Brief</strong> view.</li>
          <li><strong>Inspect Proposals:</strong> Select relevant customized outreach templates in the <strong>✍️ Proposals Ready</strong> view.</li>
          <li><strong>Submit Outreach:</strong> Customize proposals and contact prospects directly through platform job links.</li>
          <li><strong>Continuous Discovery:</strong> Automated scheduled runs poll active platforms hourly to surface new leads.</li>
        </ol>
      </section>
    </section>

    <!-- VIEW 2: PROPOSALS READY -->
    <section id="view-proposals" style="display:none;">
      <div id="propCardsContainer">
        {"".join(proposal_cards_html)}
      </div>
    </section>

    <!-- VIEW 3: 6-TRACK RADAR & MSSP VENDOR SCORECARD -->
    <section id="view-radar" style="display:none;">
      <div class="opp-card" style="border-left-color:#0084b8;">
        <h2 style="margin-top:0;">🗺️ Registered 6-Track Radar Coverage ({total_platforms} Active Portals)</h2>
        <p style="color:#475569;font-size:0.92em;">Polled automatically via Clustered Portal Dorks, JSON APIs, and XML/Atom RSS Feeds with Dead-Platform Circuit Breaker (<em>joinstellar.ai / Stellar AI blacklisted</em>).</p>
        <div class="radar-grid">
          <div class="radar-box">
            <h4>🤝 Track A: Direct B2B &amp; Fractional MSP (6 Portals)</h4>
            <p>Upwork (Managed Services &amp; Cloud), Intch, Contra, Wellfound (AngelList Talent), Catalant, YunoJuno.</p>
          </div>
          <div class="radar-box">
            <h4>🤖 Track B: Category 1 — AI Evaluation &amp; RLHF (20 Portals)</h4>
            <p>Outlier AI, Alignerr, DataAnnotation.tech, Mindrift, Innodata, OneForma, Mercor, OpenTrain AI, Surge AI, Pareto AI, Micro1, RWS TrainAI, TELUS Digital, Peroptyx, TransPerfect DataForce, Welocalize, Appen CrowdGen, LXT, RemoExperts, Awesome AI Jobs.</p>
          </div>
          <div class="radar-box">
            <h4>🌎 Track C: Category 2 — Vetted Global &amp; LATAM Networks (16)</h4>
            <p>Toptal, Turing, Revelo, Lemon.io, Proxify, Braintrust, Arc.dev, Gun.io, Tecla, Strider, NeuronHire, HiresLink, Interfell, BairesDev, Nearsure, CloudDevs.</p>
          </div>
          <div class="radar-box">
            <h4>🇫🇷 Track D: Category 3 — Francophone &amp; European Portals (9)</h4>
            <p>Freelancermap, Free-Work (ex Freelance-Info), LeHibou, Freelance-Informatique, Malt, Comet, Crème de la Crème, Codeur.com, 9am.works.</p>
          </div>
          <div class="radar-box">
            <h4>🎙️ Track E: Category 5 — Executive Expert Networks ($150–$400/hr)</h4>
            <p>GLG (Gerson Lehrman Group), AlphaSights, Guidepoint, Dialectica, Wynter (B2B SaaS Panels), Respondent.io.</p>
          </div>
          <div class="radar-box">
            <h4>📡 Track F: Category 6 — Curated Remote Boards &amp; APIs (15)</h4>
            <p>Working Nomads API, Himalayas API &amp; RSS, Remotive API, Jobicy API, RemoteOK API, We Work Remotely RSS, Real Work From Anywhere RSS, The Nonlinear Project, FlexJobs, Remote.co, 4DayWeek.io, DevOpsProjectsHQ, FindJobIT, DistantJob, WOW Remote Teams.</p>
          </div>
        </div>
      </div>

      <div class="opp-card" style="border-left-color:#10b981;">
        <h2 style="margin-top:0;">📊 Instant MSSP Cybersecurity &amp; RMM Vendor Scorecard (Track E Live Call Reference)</h2>
        <div class="radar-grid">
          {"".join(scorecard_items_html)}
        </div>
      </div>
    </section>

    <!-- VIEW 4: RAW MARKDOWN -->
    <section id="view-markdown" style="display:none;">
      <div class="opp-card">
        <div class="opp-header">
          <h3 class="opp-title">📄 morning_brief.md</h3>
          <button type="button" class="btn-action btn-primary" onclick="copyText('rawBriefMdContent', this)">📋 Copy morning_brief.md</button>
        </div>
        <pre id="rawBriefMdContent" class="proposal-box">{html.escape(brief_md)}</pre>
      </div>
      <div class="opp-card">
        <div class="opp-header">
          <h3 class="opp-title">📄 proposals_ready.md</h3>
          <button type="button" class="btn-action btn-primary" onclick="copyText('rawPropMdContent', this)">📋 Copy proposals_ready.md</button>
        </div>
        <pre id="rawPropMdContent" class="proposal-box">{html.escape(proposals_md)}</pre>
      </div>
    </section>

    <footer>
      Scout &amp; Analyst Career Automation Suite v4.0.0 &mdash;
      Autonomous Multi-Track Career Pipeline &amp; Proposal Engine
    </footer>
  </main>

  <script>
    let currentVerdict = 'ALL';
    let currentTrack = 'ALL';

    function toggleSidebar() {{
      const isCollapsed = document.body.classList.toggle('sidebar-collapsed');
      try {{
        localStorage.setItem('scout_sidebar_collapsed', isCollapsed ? '1' : '0');
      }} catch (e) {{}}
    }}

    function toggleNavGroup(groupName, headerEl, forceFolded) {{
      const isFolded = (typeof forceFolded === 'boolean')
        ? forceFolded
        : !headerEl.classList.contains('folded');
      headerEl.classList.toggle('folded', isFolded);
      document.querySelectorAll('#navbar li.nav-group-item[data-group="' + groupName + '"]').forEach(li => {{
        li.classList.toggle('folded-item', isFolded);
      }});
      try {{
        localStorage.setItem('scout_nav_group_' + groupName, isFolded ? '1' : '0');
      }} catch (e) {{}}
    }}

    (function restoreSidebarState() {{
      try {{
        if (localStorage.getItem('scout_sidebar_collapsed') === '1') {{
          document.body.classList.add('sidebar-collapsed');
        }}
        ['views', 'tracks', 'links', 'matches'].forEach(g => {{
          if (localStorage.getItem('scout_nav_group_' + g) === '1') {{
            const hdr = document.querySelector('#navbar li.nav-group-header[data-group-toggle="' + g + '"]');
            if (hdr) toggleNavGroup(g, hdr, true);
          }}
        }});
      }} catch (e) {{}}
    }})();

    document.addEventListener('keydown', function(e) {{
      if (e.key === '[' && !['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target && e.target.tagName) || '')) {{
        toggleSidebar();
      }}
    }});

    function switchMainView(viewName) {{
      document.getElementById('view-brief').style.display = (viewName === 'brief') ? '' : 'none';
      document.getElementById('view-proposals').style.display = (viewName === 'proposals') ? '' : 'none';
      document.getElementById('view-radar').style.display = (viewName === 'radar') ? '' : 'none';
      document.getElementById('view-markdown').style.display = (viewName === 'markdown') ? '' : 'none';

      document.getElementById('tab-view-brief').classList.toggle('active', viewName === 'brief');
      document.getElementById('tab-view-proposals').classList.toggle('active', viewName === 'proposals');
      document.getElementById('tab-view-radar').classList.toggle('active', viewName === 'radar');
      document.getElementById('tab-view-markdown').classList.toggle('active', viewName === 'markdown');

      document.getElementById('nav-brief').classList.toggle('active-nav', viewName === 'brief');
      document.getElementById('nav-proposals').classList.toggle('active-nav', viewName === 'proposals');
      document.getElementById('nav-radar').classList.toggle('active-nav', viewName === 'radar');
      document.getElementById('nav-markdown').classList.toggle('active-nav', viewName === 'markdown');
    }}

    function toggleInlineProposal(jhash) {{
      const el = document.getElementById('inline-prop-' + jhash);
      if (el) el.classList.toggle('open');
    }}

    function jumpToProposal(jhash) {{
      switchMainView('proposals');
      const target = document.getElementById('job-' + jhash);
      if (target) {{
        target.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}

    function switchLang(prefixHash, lang, btn) {{
      const container = btn.closest('.opp-card') || btn.parentElement.parentElement;
      btn.parentElement.querySelectorAll('.btn-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      ['en', 'fr', 'es', 'adv'].forEach(l => {{
        const pane = container.querySelector('.lang-' + l + '-' + prefixHash);
        if (pane) {{
          pane.style.display = (lang === 'all' || lang === l) ? 'block' : 'none';
        }}
      }});
    }}

    function filterCards(verdict) {{
      currentVerdict = verdict;
      document.querySelectorAll('#verdictFilterBar .btn-tab[data-filter]').forEach(btn => {{
        btn.classList.toggle('active', btn.getAttribute('data-filter') === verdict);
      }});
      applyFilters();
    }}

    function filterByTrack(trackCode) {{
      currentTrack = trackCode;
      const sel = document.getElementById('trackFilterSelect');
      if (sel && sel.value !== trackCode) {{
        sel.value = trackCode;
      }}
      applyFilters();
    }}

    function applyFilters() {{
      const q = (document.getElementById('searchInput').value || '').toLowerCase();
      document.querySelectorAll('.brief-card, .prop-card').forEach(card => {{
        const v = card.getAttribute('data-verdict');
        const t = card.getAttribute('data-track') || 'OTHER';
        const matchesVerdict = (currentVerdict === 'ALL') || (v === currentVerdict);
        const matchesTrack = (currentTrack === 'ALL') || (t === currentTrack);
        const matchesQuery = !q || card.innerText.toLowerCase().includes(q);
        card.style.display = (matchesVerdict && matchesTrack && matchesQuery) ? '' : 'none';
      }});
    }}

    function copyText(elementId, btn) {{
      const text = document.getElementById(elementId).innerText;
      navigator.clipboard.writeText(text).then(() => {{
        const orig = btn.innerText;
        btn.innerText = '✅ Copied!';
        setTimeout(() => {{ btn.innerText = orig; }}, 1800);
      }});
    }}
  </script>
</body>
</html>"""


def run_analyst(re_score_all: bool = False, web_dir: Optional[str] = None) -> None:
    profile = load_json(PROFILE_PATH)
    cfg = load_json(CONFIG_PATH)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_db_schema(conn)

    query = (
        "SELECT * FROM opportunities"
        if re_score_all
        else "SELECT * FROM opportunities WHERE verdict IS NULL OR (verdict IN ('APPLY', 'POSSIBLE') AND (proposal_en IS NULL OR proposal_en = ''))"
    )
    rows = conn.execute(query).fetchall()
    print(f"[ANALYST] Evaluating {len(rows)} opportunities against {PROFILE_PATH.name} (v4.0.0)...")

    for row in rows:
        row_dict = dict(row)
        res = evaluate_opportunity(row_dict, profile)
        merged_dict = {**row_dict, **res}
        p_en, p_fr, p_es, p_adv = ("", "", "", "")
        if res["verdict"] in ("APPLY", "POSSIBLE"):
            p_en, p_fr, p_es, p_adv, _ = build_proposal_bundle(merged_dict, profile)

        conn.execute(
            """
            UPDATE opportunities
               SET status = 'EVALUATED',
                   verdict = ?,
                   total_score = ?,
                   tech_score = ?,
                   safety_score = ?,
                   geo_lang_score = ?,
                   contract_score = ?,
                   matched_skills = ?,
                   missing_gaps = ?,
                   red_flags = ?,
                   analyst_notes = ?,
                   proposal_en = ?,
                   proposal_fr = ?,
                   proposal_es = ?,
                   proposal_advisory = ?
             WHERE job_hash = ?
            """,
            (
                res["verdict"],
                res["total_score"],
                res["tech_score"],
                res["safety_score"],
                res["geo_lang_score"],
                res["contract_score"],
                res["matched_skills"],
                res["missing_gaps"],
                res["red_flags"],
                res["analyst_notes"],
                p_en,
                p_fr,
                p_es,
                p_adv,
                row_dict["job_hash"],
            ),
        )
    conn.commit()

    all_rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM opportunities ORDER BY total_score DESC, discovered_at DESC"
        ).fetchall()
    ]

    apply_rows = [r for r in all_rows if r["verdict"] == "APPLY"]
    possible_rows = [r for r in all_rows if r["verdict"] == "POSSIBLE"]
    skip_rows = [r for r in all_rows if r["verdict"] == "SKIP"]

    today_str = datetime.date.today().isoformat()
    updated_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_platforms = len(cfg.get("platforms", []))

    # 1. Write morning_brief.md (v4.0.0 format)
    brief_lines = [
        f"# 🎯 Morning Professional Briefing — {today_str}",
        f"**Engine Version:** SCOUT + ANALYST v4.0.0 | **Monitored Portals:** {total_platforms} Active Platforms | **Web Portal:** {PUBLIC_TUNNEL_URL}",
        "**Workflow:** Review prioritized opportunities, inspect trilingual proposals, and initiate outreach.",
        "",
        "## 📊 Pipeline Summary",
        f"- **🔥 APPLY (Score >= 80):** {len(apply_rows)} high-alignment leads",
        f"- **🟡 POSSIBLE (Score 62–79):** {len(possible_rows)} secondary/caveat leads",
        f"- **⏭️ SKIP (Score < 62):** {len(skip_rows)} filtered out automatically",
        "",
        "## 🔥 Top Priority Actions (APPLY — Score >= 80)",
    ]

    if apply_rows:
        brief_lines.extend(
            [
                "| Score | Track | Platform / Company | Role / Opportunity | Breakdown (Tech/Role/Geo/Cont) |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for r in apply_rows[:20]:
            bd = f"{r['tech_score']}/{r['safety_score']}/{r['geo_lang_score']}/{r['contract_score']}"
            brief_lines.append(
                f"| **{r['total_score']}/100** | {r['track']} | **{r['platform_name']}** ({r['company']}) | [{r['title']}]({r['url']}) | `{bd}` |"
            )
    else:
        brief_lines.append("_No new APPLY leads today._")

    brief_lines.extend(["", "## 🟡 Secondary / Caveat Queue (POSSIBLE — Score 62–79)"])
    if possible_rows:
        brief_lines.extend(
            [
                "| Score | Track | Platform / Company | Role / Opportunity | Analyst Caveat / Notes |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
        )
        for r in possible_rows[:20]:
            brief_lines.append(
                f"| **{r['total_score']}/100** | {r['track']} | **{r['platform_name']}** ({r['company']}) | [{r['title']}]({r['url']}) | {r['analyst_notes']} |"
            )
    else:
        brief_lines.append("_No POSSIBLE leads queued._")

    brief_lines.extend(["", "## ⏭️ Skipped Opportunities (Score Below Threshold)"])
    if skip_rows:
        for r in skip_rows:
            brief_lines.append(
                f"- **[SKIP — {r['total_score']}/100]** `{r['platform_name']}` ({r['company']}) — *{r['title']}* ({r['analyst_notes']})"
            )
    else:
        brief_lines.append("_No skipped leads logged._")

    brief_lines.extend(
        [
            "",
            f"## 🗺️ Registered 6-Track Radar Coverage ({total_platforms} Active Portals)",
            "- **Track A (Direct B2B & Fractional MSP — 6 Portals):** Upwork (Managed Services & Cloud), Intch, Contra, Wellfound, Catalant, YunoJuno.",
            "- **Track B (Category 1 — 20 AI Evaluation & RLHF Portals):** Outlier AI, Alignerr, DataAnnotation, Mindrift, Innodata, OneForma, Mercor, OpenTrain AI, Surge AI, Pareto AI, Micro1, RWS TrainAI, TELUS Digital, Peroptyx, TransPerfect DataForce, Welocalize, Appen CrowdGen, LXT, RemoExperts, Awesome AI Jobs. *(Stellar AI blacklisted)*.",
            "- **Track C (Category 2 — 16 Vetted Global & LATAM Networks):** Toptal, Turing, Revelo, Lemon.io, Proxify, Braintrust, Arc.dev, Gun.io, Tecla, Strider, NeuronHire, HiresLink, Interfell, BairesDev, Nearsure, CloudDevs.",
            "- **Track D (Category 3 — 9 Francophone & European IT Portals):** Freelancermap, Free-Work, LeHibou, Freelance-Informatique, Malt, Comet, Crème de la Crème, Codeur.com, 9am.works.",
            "- **Track E (Category 5 — 6 Executive Expert Networks):** GLG, AlphaSights, Guidepoint, Dialectica, Wynter, Respondent.io.",
            "- **Track F (Category 6 — 16 Curated Remote Boards & APIs):** Working Nomads API, Himalayas API/RSS, Remotive API, Jobicy API, RemoteOK API, We Work Remotely RSS, Real Work From Anywhere RSS, The Nonlinear Project, FlexJobs, Remote.co, 4DayWeek.io, DevOpsProjectsHQ, FindJobIT, DistantJob, WOW Remote Teams.",
        ]
    )

    brief_md_content = "\n".join(brief_lines) + "\n"
    with open(BRIEF_PATH, "w", encoding="utf-8") as f:
        f.write(brief_md_content)

    # 2. Write proposals_ready.md
    prop_lines = [
        f"# 📝 Trilingual Proposals & Advisory Pitches — {today_str}",
        f"Generated automatically by `analyst_agent.py` v4.0.0 using verified metrics from `master_profile.json` · Live Portal: {PUBLIC_TUNNEL_URL}",
        "",
    ]
    actionable = apply_rows + possible_rows
    for r in actionable:
        prop_lines.append(generate_trilingual_proposals(r, profile))

    prop_md_content = "\n".join(prop_lines) + "\n"
    with open(PROPOSALS_PATH, "w", encoding="utf-8") as f:
        f.write(prop_md_content)

    # 3. Build & write unified index.html
    index_html_content = build_unified_index_html(
        today_str=today_str,
        updated_ts=updated_ts,
        apply_rows=apply_rows,
        possible_rows=possible_rows,
        skip_rows=skip_rows,
        brief_md=brief_md_content,
        proposals_md=prop_md_content,
        profile=profile,
        cfg=cfg,
        public_url=PUBLIC_TUNNEL_URL,
    )
    with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(index_html_content)

    print(
        f"[ANALYST] Scored {len(rows)} rows. Totals -> APPLY: {len(apply_rows)}, "
        f"POSSIBLE: {len(possible_rows)}, SKIP: {len(skip_rows)}."
    )
    print(f"[ANALYST] Wrote {BRIEF_PATH.name}, {PROPOSALS_PATH.name}, and unified {INDEX_HTML_PATH.name}.")

    # 4. Sync index.html to configured web root if available
    target_web_dir = resolve_nginx_web_dir(web_dir)
    if target_web_dir:
        try:
            dest_index = os.path.join(target_web_dir, INDEX_HTML_PATH.name)
            shutil.copyfile(str(INDEX_HTML_PATH), dest_index)
            print(f"[NGINX SYNC] Published unified {INDEX_HTML_PATH.name} to {dest_index} (live at {PUBLIC_TUNNEL_URL})")
        except Exception as exc:
            print(f"[!] Warning: Could not copy {INDEX_HTML_PATH.name} to {target_web_dir}: {exc}")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="ANALYST Agent v4.0.0 — 6-Track Scoring, Trilingual Proposal Engine & Nginx Publisher"
    )
    parser.add_argument("--run", action="store_true", help="Evaluate new rows and generate reports + index.html")
    parser.add_argument("--rescore-all", action="store_true", help="Re-score all rows in career_ops.db")
    parser.add_argument("--web-dir", default=None, help="Optional web root directory (defaults to /var/www/html)")
    args = parser.parse_args()
    run_analyst(re_score_all=args.rescore_all, web_dir=args.web_dir)

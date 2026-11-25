"""Watch chosen subreddits for fresh posts where someone is asking for help
with automation, admin or lead handling, and post them to Discord.

Run:  python leads.py             (needs DISCORD_WEBHOOK_URL)
      python leads.py --dry-run   (prints matches, sends nothing, saves nothing)

Uses Reddit's official API when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are
set (needed on GitHub Actions, Reddit blocks anonymous cloud requests). Without
them it uses the public JSON endpoints, which work from a home connection.

The bot only finds posts. Every reply or email is written by a person.
Posts are tagged EMAILABLE only when the poster shared a website or business
link themselves; anonymous posters are never looked up elsewhere.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

SEEN_FILE = Path(__file__).with_name("seen_posts.json")
UA = {"User-Agent": "python:reddit-leads:v1.0 (personal lead alerts)"}
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "6"))

SUBREDDITS = [
    "smallbusiness", "Entrepreneur", "sweatystartup", "realtors", "RealEstate",
    "n8n", "automation", "zapier", "agency", "msp", "Bookkeeping", "ecommerce",
    "HVAC", "Plumbing", "Roofing", "LawFirm",
]

# Komtora non-solicit: never surface freight / logistics prospects.
EXCLUDE = re.compile(r"freight|forwarder|logistic|customs broker|\b3pl\b|shipping agen", re.I)

# Buying intent: someone asking for a tool, a person, or a fix.
INTENT = re.compile(
    r"any(one|body)\s+(got\s+|have\s+)?(recommend|recs?\b|suggest)"
    r"|looking for (a|an|someone|help|recommend)"
    r"|alternative to|recommendations? for|who (do|should) (i|we) hire"
    r"|need (help|someone|a (dev|developer|freelancer|consultant|tool))"
    r"|hire (a|an|someone)|got burned by|worth it\?|how do (i|you|we) automate"
    r"|is there a (tool|way|app)|can (anyone|someone) help",
    re.I,
)

# What we sell: automation, AI assistants, lead follow-up, admin, invoices.
TOPIC = re.compile(
    r"automat|zapier|make\.com|n8n|workflow|chatbot|ai (agent|assistant|receptionist)"
    r"|\bcrm\b|follow[- ]?ups?|missed (calls?|leads?)|lead (response|management|follow)"
    r"|speed to lead|chasing invoices|overdue invoices|invoice reminders?|admin work"
    r"|manual (data|entry|work)|whatsapp (bot|automation|api)|booking system|intake",
    re.I,
)

URL = re.compile(r"https?://[^\s)\]]+", re.I)
SKIP_DOMAINS = ("reddit.com", "redd.it", "imgur.com", "youtube.com", "youtu.be",
                "zapier.com", "n8n.io", "make.com", "google.com", "docs.google")


# ---------- reddit access ----------

def session() -> tuple[requests.Session, str]:
    s = requests.Session()
    s.headers.update(UA)
    cid, sec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if cid and sec:
        r = s.post("https://www.reddit.com/api/v1/access_token",
                   auth=(cid, sec), data={"grant_type": "client_credentials"}, timeout=30)
        r.raise_for_status()
        s.headers["Authorization"] = f"bearer {r.json()['access_token']}"
        return s, "https://oauth.reddit.com"
    return s, "https://www.reddit.com"


def fetch_new(s: requests.Session, base: str, sub: str) -> list[dict]:
    url = f"{base}/r/{sub}/new" + ("" if "oauth" in base else ".json")
    for attempt in range(3):
        r = s.get(url, params={"limit": 100, "raw_json": 1}, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (403, 404):
            print(f"[warn] r/{sub}: {r.status_code}, skipped")
            return []
        r.raise_for_status()
        return [c["data"] for c in r.json()["data"]["children"]]
    print(f"[warn] r/{sub}: rate limited, skipped")
    return []


# ---------- matching ----------

def business_links(p: dict) -> list[str]:
    text = f"{p.get('title', '')} {p.get('selftext', '')} {'' if p.get('is_self') else p.get('url', '')}"
    out = []
    for u in URL.findall(text):
        u = u.rstrip(".,;:!?'\"")
        if not any(d in u.lower() for d in SKIP_DOMAINS) and u not in out:
            out.append(u)
    return out[:3]


def match(p: dict, now: float) -> dict | None:
    age_h = (now - p["created_utc"]) / 3600
    if age_h > MAX_AGE_HOURS or p.get("stickied") or p.get("over_18"):
        return None
    text = f"{p.get('title', '')}\n{p.get('selftext', '')}"
    if EXCLUDE.search(text):
        return None
    intent, topic = INTENT.search(text), TOPIC.search(text)
    if not intent or not topic:
        return None
    return {
        "id": p["name"],
        "sub": p["subreddit"],
        "title": p["title"],
        "snippet": re.sub(r"\s+", " ", p.get("selftext", ""))[:300],
        "link": "https://www.reddit.com" + p["permalink"],
        "age_h": round(age_h, 1),
        "comments": p.get("num_comments", 0),
        "business_links": business_links(p),
        "intent": intent.group(0),
        "topic": topic.group(0),
    }


# ---------- output ----------

def post_discord(lead: dict) -> None:
    hook = os.environ["DISCORD_WEBHOOK_URL"]
    tag = "EMAILABLE" if lead["business_links"] else "REPLY ONLY"
    fields = [
        {"name": "Age", "value": f"{lead['age_h']}h, {lead['comments']} comments", "inline": True},
        {"name": "Signals", "value": f"{lead['intent']} / {lead['topic']}"[:200], "inline": True},
    ]
    if lead["business_links"]:
        fields.append({"name": "Their links", "value": "\n".join(lead["business_links"])[:1000]})
    embed = {
        "title": f"[{tag}] r/{lead['sub']}: {lead['title']}"[:256],
        "url": lead["link"],
        "description": lead["snippet"] or "(no body text)",
        "color": 0x2E7D32 if lead["business_links"] else 0x607D8B,
        "fields": fields,
    }
    for _ in range(3):
        r = requests.post(hook, json={"embeds": [embed]}, timeout=30)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)))
            continue
        r.raise_for_status()
        return


def load_seen() -> dict:
    try:
        return json.loads(SEEN_FILE.read_text())
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    s, base = session()
    print(f"Using {'official API' if 'oauth' in base else 'public JSON'}")
    now = time.time()
    seen = load_seen()
    leads = []
    for sub in SUBREDDITS:
        for p in fetch_new(s, base, sub):
            lead = match(p, now)
            if lead and lead["id"] not in seen:
                leads.append(lead)
        time.sleep(1 if "oauth" in base else 2)

    leads.sort(key=lambda l: (not l["business_links"], l["age_h"]))
    print(f"{len(leads)} new leads")
    for l in leads:
        tag = "EMAILABLE" if l["business_links"] else "reply only"
        print(f"- [{tag}] r/{l['sub']} ({l['age_h']}h) {l['title']}\n  {l['link']}")
        if not args.dry_run:
            post_discord(l)
            seen[l["id"]] = int(now)

    if not args.dry_run:
        cutoff = now - 7 * 86400
        seen = {k: v for k, v in seen.items() if v > cutoff}
        SEEN_FILE.write_text(json.dumps(seen, indent=0, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

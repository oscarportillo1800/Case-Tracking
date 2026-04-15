"""
Just Security Trump Litigation Tracker scraper.

Source: https://www.justsecurity.org/trump-litigation-tracker/

Just Security maintains a manually curated, editorially vetted table of federal
litigation against the Trump administration.  We scrape the public tracker page,
extract case rows, and normalise them into our internal schema.

Because Just Security does not expose a public API, this module uses HTML
parsing.  We parse responsibly (single pass, no hammering) and clearly attribute
every record to Just Security as the source.
"""

import logging
import re
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TRACKER_URL = "https://www.justsecurity.org/trump-litigation-tracker/"
SOURCE_NAME = "Just Security"

# Just Security embeds some tracker data in an Airtable iframe or a custom
# HTML table.  We attempt both extraction paths.
AIRTABLE_EMBED_RE = re.compile(r'src=["\']([^"\']*airtable[^"\']*)["\']', re.IGNORECASE)


def _get_page(url: str) -> Optional[str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; FederalLitigationTracker/1.0; "
            "+https://github.com/oscarportillo1800/case-tracking)"
        )
    }
    for attempt in range(4):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == 3:
                logger.error("Just Security fetch failed after retries: %s", exc)
                return None
            wait = 2 ** attempt
            logger.warning("Just Security fetch failed (%s), retry in %ss", exc, wait)
            time.sleep(wait)
    return None


def _parse_date(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%B %Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _classify(description: str) -> str:
    d = description.lower()
    if "foia" in d or "freedom of information" in d:
        return "FOIA"
    if "administrative procedure" in d or " apa " in d:
        return "APA"
    if "habeas" in d:
        return "Habeas Corpus"
    if "first amendment" in d:
        return "First Amendment"
    if "immigration" in d or "deportation" in d:
        return "Immigration"
    if "due process" in d:
        return "Due Process"
    if "civil rights" in d:
        return "Civil Rights"
    return "Federal Litigation"


def _org_flags(text: str) -> dict:
    t = text.lower()
    return {
        "involves_democracy_forward": any(
            x in t for x in ["democracy forward", "democracy forward foundation"]
        ),
        "involves_aclu": any(
            x in t
            for x in [
                "aclu",
                "american civil liberties union",
                "new york civil liberties",
                "aclu foundation",
            ]
        ),
        "involves_democracy_defenders": "democracy defenders" in t,
        "involves_public_citizen": "public citizen" in t,
        "involves_protect_democracy": "protect democracy" in t,
        "names_federal_defendant": any(
            x in t
            for x in [
                "trump",
                "united states",
                "department of",
                "federal",
                "doge",
                "government efficiency",
            ]
        ),
    }


def _parse_html_table(soup: BeautifulSoup) -> list:
    """
    Attempt to extract cases from an HTML <table> on the page.
    Just Security sometimes renders a table with columns like:
      Case Name | Court | Date Filed | Issue | Status | Description
    """
    cases = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        # Try to identify header row
        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(kw in " ".join(header_cells) for kw in ["case", "court", "filed", "date"]):
            continue
        # Map column indices
        col = {}
        for i, h in enumerate(header_cells):
            if "case" in h and "name" in h:
                col["case_name"] = i
            elif "case" in h and "number" in h:
                col["case_number"] = i
            elif "court" in h:
                col["court"] = i
            elif "filed" in h or "date" in h:
                col["date_filed"] = i
            elif "issue" in h or "type" in h or "topic" in h:
                col["case_type"] = i
            elif "plaintiff" in h:
                col["plaintiff"] = i
            elif "defendant" in h:
                col["defendant"] = i
            elif "description" in h or "status" in h or "summary" in h:
                col["description"] = i

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            def cell(key):
                idx = col.get(key)
                if idx is None or idx >= len(cells):
                    return ""
                return cells[idx].get_text(separator=" ", strip=True)

            case_name = cell("case_name") or cell("description") or "Unknown"
            if len(case_name) < 3:
                continue

            raw_date = cell("date_filed")
            date_filed = _parse_date(raw_date) if raw_date else None

            description = cell("description")
            case_type_raw = cell("case_type")
            case_type = _classify(case_type_raw + " " + description)

            plaintiff = cell("plaintiff")
            defendant = cell("defendant")
            court = cell("court")

            # Extract any hyperlink as the source URL
            link_tag = cells[col["case_name"]].find("a") if "case_name" in col and col["case_name"] < len(cells) else None
            source_url = link_tag["href"] if link_tag and link_tag.get("href") else TRACKER_URL

            full_text = " ".join([case_name, plaintiff, defendant, court, description])
            flags = _org_flags(full_text)

            cases.append({
                "case_name": case_name,
                "case_number": cell("case_number"),
                "court": court,
                "court_level": _map_court_level(court),
                "docket_url": None,
                "docket_id": None,
                "case_type": case_type,
                "cause_of_action": case_type_raw,
                "nature_of_suit": "",
                "plaintiff": plaintiff,
                "defendant": defendant,
                "date_filed": date_filed,
                "date_terminated": None,
                "source": SOURCE_NAME,
                "source_url": source_url,
                **flags,
            })
    return cases


def _map_court_level(court: str) -> str:
    c = court.lower()
    if "supreme" in c:
        return "Supreme Court"
    if any(x in c for x in ["circuit", "appeals", "appellate"]):
        return "Circuit Court"
    if "district" in c or "d." in c:
        return "District Court"
    return "District Court"


def fetch_all() -> list:
    """
    Fetch and return all cases from the Just Security Trump Litigation Tracker.
    Returns a list of normalised case dicts.
    """
    logger.info("Fetching Just Security litigation tracker: %s", TRACKER_URL)
    html = _get_page(TRACKER_URL)
    if not html:
        logger.warning("Just Security: no HTML returned, skipping.")
        return []

    soup = BeautifulSoup(html, "lxml")

    # Primary path: HTML table on the page
    cases = _parse_html_table(soup)

    # Fallback: look for article-style list entries if no table found
    if not cases:
        cases = _parse_article_entries(soup)

    logger.info("Just Security: extracted %d cases", len(cases))
    return cases


def _parse_article_entries(soup: BeautifulSoup) -> list:
    """
    Fallback parser for list/article-style tracker pages.
    Looks for structured div or li blocks that describe individual cases.
    """
    cases = []
    # Look for common CMS patterns: divs with class containing 'case', 'entry', 'row'
    candidates = soup.find_all(
        lambda tag: tag.name in ["div", "li", "article"]
        and any(
            kw in " ".join(tag.get("class", [])).lower()
            for kw in ["case", "entry", "row", "item", "record"]
        )
    )
    for el in candidates:
        text = el.get_text(separator=" ", strip=True)
        if len(text) < 20:
            continue
        link_tag = el.find("a")
        source_url = link_tag["href"] if link_tag and link_tag.get("href") else TRACKER_URL
        case_name = link_tag.get_text(strip=True) if link_tag else text[:120]
        flags = _org_flags(text)
        cases.append({
            "case_name": case_name,
            "case_number": None,
            "court": None,
            "court_level": "District Court",
            "docket_url": None,
            "docket_id": None,
            "case_type": _classify(text),
            "cause_of_action": "",
            "nature_of_suit": "",
            "plaintiff": "",
            "defendant": "",
            "date_filed": None,
            "date_terminated": None,
            "source": SOURCE_NAME,
            "source_url": source_url,
            **flags,
        })
    return cases

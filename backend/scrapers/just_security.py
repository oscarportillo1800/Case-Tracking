"""
Just Security Trump Litigation Tracker scraper.

Source: https://www.justsecurity.org/trump-litigation-tracker/

Just Security maintains a manually curated, editorially vetted table of federal
litigation against the Trump administration.

DATE FLOOR: Cases dated before 2025-01-20 are discarded.
"""

import logging
import re
import time
from datetime import date, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TRACKER_URL = "https://www.justsecurity.org/trump-litigation-tracker/"
SOURCE_NAME = "Just Security"

DATE_FLOOR = date(2025, 1, 20)


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


def _parse_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
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
    if any(x in d for x in [
        "tariff", "ieepa", "international emergency economic powers",
        "section 232", "section 301", "section 201", "customs", "trade remedy",
    ]):
        return "Tariff / Trade"
    if "first amendment" in d:
        return "First Amendment"
    if "immigration" in d or "deportation" in d:
        return "Immigration"
    if "due process" in d:
        return "Due Process"
    if "civil rights" in d:
        return "Civil Rights"
    return "Federal Litigation"


def _map_court_level(court: str) -> str:
    c = (court or "").lower()
    if "supreme" in c:
        return "Supreme Court"
    if any(x in c for x in ["circuit", "appeals", "appellate"]):
        return "Circuit Court"
    if "federal claims" in c or "claims court" in c:
        return "Court of Federal Claims"
    if "international trade" in c:
        return "Court of International Trade"
    return "District Court"


def _org_flags(text: str) -> dict:
    t = text.lower()
    return {
        "involves_democracy_forward": any(
            x in t for x in ["democracy forward", "democracy forward foundation"]
        ),
        "involves_aclu": any(
            x in t for x in [
                "aclu", "american civil liberties union",
                "new york civil liberties", "aclu foundation",
            ]
        ),
        "involves_democracy_defenders": "democracy defenders" in t,
        "involves_public_citizen": "public citizen" in t,
        "involves_protect_democracy": "protect democracy" in t,
        "names_federal_defendant": any(
            x in t for x in [
                "trump", "united states", "department of", "federal",
                "doge", "government efficiency", "ustr", "customs", "trade representative",
            ]
        ),
    }


def _parse_html_table(soup: BeautifulSoup) -> list:
    cases = []
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [th.get_text(strip=True).lower() for th in rows[0].find_all(["th", "td"])]
        if not any(kw in " ".join(header_cells) for kw in ["case", "court", "filed", "date"]):
            continue
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

            # Enforce date floor
            if date_filed and date_filed < DATE_FLOOR:
                continue
            # If date unknown, still include — likely a new case
            # (Just Security only tracks Trump-term 2 cases)

            description = cell("description")
            case_type_raw = cell("case_type")
            case_type = _classify(case_type_raw + " " + description)

            plaintiff = cell("plaintiff")
            defendant = cell("defendant")
            court = cell("court")

            link_tag = (
                cells[col["case_name"]].find("a")
                if "case_name" in col and col["case_name"] < len(cells) else None
            )
            source_url = (
                link_tag["href"] if link_tag and link_tag.get("href") else TRACKER_URL
            )

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
                "complaint_url": None,
                "complaint_pdf_url": None,
                "date_filed": date_filed,
                "date_terminated": None,
                "source": SOURCE_NAME,
                "source_url": source_url,
                **flags,
            })
    return cases


def _parse_article_entries(soup: BeautifulSoup) -> list:
    cases = []
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
            "complaint_url": None,
            "complaint_pdf_url": None,
            "date_filed": None,
            "date_terminated": None,
            "source": SOURCE_NAME,
            "source_url": source_url,
            **flags,
        })
    return cases


def fetch_all() -> list:
    """
    Fetch all cases from the Just Security Trump Litigation Tracker.
    Returns a list of normalised case dicts, filtered to >= 2025-01-20.
    """
    logger.info("Fetching Just Security tracker: %s", TRACKER_URL)
    html = _get_page(TRACKER_URL)
    if not html:
        logger.warning("Just Security: no HTML returned, skipping.")
        return []

    soup = BeautifulSoup(html, "lxml")
    cases = _parse_html_table(soup)
    if not cases:
        cases = _parse_article_entries(soup)

    logger.info("Just Security: %d cases extracted", len(cases))
    return cases

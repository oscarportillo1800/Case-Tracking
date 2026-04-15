"""
Civil Rights Litigation Clearinghouse (CRLC) scraper.

Source: https://clearinghouse.net

University of Michigan Law School's rigorously vetted civil rights/liberties
federal case repository.

DATE FLOOR: Cases dated before 2025-01-20 are discarded.
"""

import logging
import re
import time
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://clearinghouse.net"
SEARCH_URL = "https://clearinghouse.net/results.php"
SOURCE_NAME = "Michigan Clearinghouse"
DATE_FLOOR = date(2025, 1, 20)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; FederalLitigationTracker/1.0; "
        "+https://github.com/oscarportillo1800/case-tracking)"
    )
}

SEARCH_QUERIES = [
    # Priority organisations
    "Democracy Forward",
    "American Civil Liberties Union",
    "ACLU",
    "Public Citizen",
    "Protect Democracy",
    "Democracy Defenders",
    # Federal defendant terms
    "Trump administration",
    "Department of Homeland Security",
    "Department of Justice",
    "Department of Education",
    "Immigration and Customs Enforcement",
    "DOGE",
    # Case-type keywords
    "Freedom of Information Act",
    "Administrative Procedure Act",
    "habeas corpus immigration",
    # Tariff / trade
    "IEEPA tariff",
    "International Emergency Economic Powers Act",
    "tariff challenge",
    "Section 232",
    "Section 301",
    "Court of Federal Claims",
]


def _get(url: str, params: Optional[dict] = None) -> Optional[str]:
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == 3:
                logger.error("Michigan Clearinghouse fetch failed: %s", exc)
                return None
            wait = 2 ** attempt
            logger.warning("Michigan Clearinghouse fetch failed (%s), retry in %ss", exc, wait)
            time.sleep(wait)
    return None


def _parse_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%d", "%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _classify(text: str) -> str:
    t = text.lower()
    if "foia" in t or "freedom of information" in t:
        return "FOIA"
    if "administrative procedure" in t or " apa " in t:
        return "APA"
    if "habeas" in t:
        return "Habeas Corpus"
    if any(x in t for x in [
        "tariff", "ieepa", "international emergency economic powers",
        "section 232", "section 301", "section 201", "customs", "trade remedy",
    ]):
        return "Tariff / Trade"
    if "first amendment" in t:
        return "First Amendment"
    if "immigration" in t or "deportation" in t or "removal" in t:
        return "Immigration"
    if "due process" in t:
        return "Due Process"
    if "civil rights" in t:
        return "Civil Rights"
    if "employment" in t or "termination" in t:
        return "Employment"
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
                "trump", "united states", "department of", "federal government",
                "doge", "government efficiency", "customs", "trade representative",
            ]
        ),
    }


def _parse_results_page(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    cases = []

    result_blocks = (
        soup.select("div.case-result")
        or soup.select("div.case")
        or soup.select("tr.case-row")
        or soup.select("li.case-item")
    )

    if not result_blocks:
        links = soup.find_all("a", href=re.compile(r"/case/\d+"))
        for link in links:
            case_name = link.get_text(strip=True)
            if not case_name or len(case_name) < 5:
                continue
            source_url = urljoin(BASE_URL, link["href"])
            flags = _org_flags(case_name)
            cases.append({
                "case_name": case_name,
                "case_number": None,
                "court": None,
                "court_level": "District Court",
                "docket_url": None,
                "docket_id": None,
                "case_type": _classify(case_name),
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

    for block in result_blocks:
        text = block.get_text(separator=" ", strip=True)
        link_tag = block.find("a")
        if not link_tag:
            continue
        case_name = link_tag.get_text(strip=True) or text[:200]
        source_url = urljoin(BASE_URL, link_tag.get("href", ""))

        court_match = re.search(r"Court[:\s]+([^\n,|]+)", text, re.IGNORECASE)
        court = court_match.group(1).strip() if court_match else ""

        date_match = re.search(
            r"Filed[:\s]+(\w+ \d{1,2},?\s*\d{4}|\d{4})", text, re.IGNORECASE
        )
        date_filed = _parse_date(date_match.group(1)) if date_match else None

        # Enforce date floor — skip known pre-2025-01-20 cases
        if date_filed and date_filed < DATE_FLOOR:
            continue

        flags = _org_flags(text)
        cases.append({
            "case_name": case_name,
            "case_number": None,
            "court": court,
            "court_level": _map_court_level(court),
            "docket_url": None,
            "docket_id": None,
            "case_type": _classify(text),
            "cause_of_action": "",
            "nature_of_suit": "",
            "plaintiff": "",
            "defendant": "",
            "complaint_url": None,
            "complaint_pdf_url": None,
            "date_filed": date_filed,
            "date_terminated": None,
            "source": SOURCE_NAME,
            "source_url": source_url,
            **flags,
        })

    return cases


def fetch_all() -> list:
    seen_urls: set = set()
    all_cases = []

    for query in SEARCH_QUERIES:
        logger.info("Michigan Clearinghouse query: %s", query)
        params = {"keyword": query, "federal": "1", "status": ""}
        html = _get(SEARCH_URL, params=params)
        if not html:
            time.sleep(1)
            continue

        cases = _parse_results_page(html)
        for case in cases:
            key = case.get("source_url") or case["case_name"]
            if key in seen_urls:
                continue
            seen_urls.add(key)
            all_cases.append(case)

        time.sleep(0.5)

    logger.info("Michigan Clearinghouse: %d unique cases fetched", len(all_cases))
    return all_cases

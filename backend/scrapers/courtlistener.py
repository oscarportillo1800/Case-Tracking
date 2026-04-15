"""
CourtListener API scraper — primary data source.

CourtListener provides free, vetted federal court data via its REST API.
API docs: https://www.courtlistener.com/api/rest/v4/

This module queries CourtListener for:
  - Federal litigation against the Trump administration / named federal defendants
  - Cases filed by Democracy Forward, ACLU, Democracy Defenders Fund,
    Public Citizen, and Protect Democracy
  - FOIA, APA, habeas, and related federal case types
"""

import logging
import os
import time
from datetime import date, datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

COURTLISTENER_BASE = "https://www.courtlistener.com/api/rest/v4"
COURTLISTENER_BASE_URL = "https://www.courtlistener.com"

# Federal courts — district, circuit, and Supreme Court
FEDERAL_COURT_TYPES = ["f", "fb", "fa", "fc"]  # CL court jurisdiction codes for federal

# Nature-of-suit codes relevant to this tracker
# 895 = Freedom of Information Act
# 890 = Other Statutory Actions (covers APA)
# 530 = Habeas Corpus (general)
# 535 = Death Penalty Habeas
# 540 = Mandamus & Other
# 550 = Civil Rights
# 555 = Prison Condition
PRIORITY_NOS_CODES = ["895", "890", "530", "535", "540", "550", "555", "560"]

# ── Key organizations ──────────────────────────────────────────────────────────
ORG_QUERIES = {
    "Democracy Forward": [
        "Democracy Forward Foundation",
        "Democracy Forward",
    ],
    "ACLU": [
        "American Civil Liberties Union",
        "ACLU Foundation",
        "ACLU Immigrants' Rights Project",
        "New York Civil Liberties",
        "ACLU of",
    ],
    "Democracy Defenders Fund": [
        "Democracy Defenders Fund",
        "Democracy Defenders",
    ],
    "Public Citizen": [
        "Public Citizen",
        "Public Citizen Litigation Group",
    ],
    "Protect Democracy": [
        "Protect Democracy",
        "Protect Democracy Project",
    ],
}

# ── Federal-defendant search terms ────────────────────────────────────────────
FEDERAL_DEFENDANT_TERMS = [
    "Donald Trump",
    "Donald J. Trump",
    "Trump Administration",
    "United States of America",
    "Department of Justice",
    "Department of Homeland Security",
    "Department of Defense",
    "Department of State",
    "Department of Education",
    "Department of Health and Human Services",
    "Department of Labor",
    "Department of Treasury",
    "Department of Transportation",
    "Department of Commerce",
    "Department of Agriculture",
    "Department of Energy",
    "Department of Housing",
    "Department of the Interior",
    "Department of Veterans Affairs",
    "Environmental Protection Agency",
    "Federal Bureau of Investigation",
    "Immigration and Customs Enforcement",
    "U.S. Customs and Border Protection",
    "Social Security Administration",
    "Office of Management and Budget",
    "Office of Personnel Management",
    "Drug Enforcement Administration",
    "Bureau of Alcohol",
    "Kash Patel",
    "Pete Hegseth",
    "Marco Rubio",
    "Pamela Bondi",
    "Scott Bessent",
    "Doug Burgum",
    "Brooke Rollins",
    "Linda McMahon",
    "Robert F. Kennedy",
    "Sean Duffy",
    "Doug Collins",
    "Russell Vought",
    "Elon Musk",
    "DOGE",
    "Department of Government Efficiency",
]

# ── FOIA / APA keyword queries ─────────────────────────────────────────────────
CASE_TYPE_QUERIES = [
    "Freedom of Information Act",
    "Administrative Procedure Act",
    "habeas corpus",
    "mandamus",
    "preliminary injunction",
    "temporary restraining order",
    "First Amendment",
    "Fifth Amendment due process",
    "unlawful termination federal employee",
    "reinstatement federal employee",
    "DOGE",
]


def _headers(api_token: Optional[str] = None) -> dict:
    h = {"Accept": "application/json"}
    token = api_token or os.getenv("COURTLISTENER_API_TOKEN")
    if token:
        h["Authorization"] = f"Token {token}"
    return h


def _get(url: str, params: dict, api_token: Optional[str] = None) -> dict:
    """GET with simple retry backoff."""
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_headers(api_token), timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            wait = 2 ** attempt
            logger.warning("CourtListener request failed (%s), retrying in %ss", exc, wait)
            time.sleep(wait)
    return {}


def _map_court_level(court_str: str) -> str:
    if not court_str:
        return "Unknown"
    c = court_str.lower()
    if "supreme" in c:
        return "Supreme Court"
    if any(x in c for x in ["circuit", "appeals", "appellate"]):
        return "Circuit Court"
    return "District Court"


def _build_docket_url(docket_id) -> str:
    return f"{COURTLISTENER_BASE_URL}/docket/{docket_id}/"


def _parse_docket(item: dict) -> dict:
    """Normalise a CourtListener docket object into our internal schema."""
    docket_id = item.get("id") or item.get("docket_id", "")
    court_name = ""
    court_obj = item.get("court") or {}
    if isinstance(court_obj, dict):
        court_name = court_obj.get("full_name") or court_obj.get("short_name", "")
    elif isinstance(court_obj, str):
        court_name = court_obj

    date_filed_raw = item.get("date_filed")
    date_filed = None
    if date_filed_raw:
        try:
            date_filed = datetime.strptime(date_filed_raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    date_terminated_raw = item.get("date_terminated")
    date_terminated = None
    if date_terminated_raw:
        try:
            date_terminated = datetime.strptime(date_terminated_raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass

    cause = item.get("cause", "") or ""
    nos = item.get("nature_of_suit", "") or ""

    return {
        "case_name": item.get("case_name", "Unknown").strip(),
        "case_number": item.get("docket_number", ""),
        "court": court_name,
        "court_level": _map_court_level(court_name),
        "docket_url": _build_docket_url(docket_id),
        "docket_id": str(docket_id),
        "case_type": _classify_case_type(cause, nos),
        "cause_of_action": cause,
        "nature_of_suit": nos,
        "plaintiff": item.get("plaintiff", "") or "",
        "defendant": item.get("defendant", "") or "",
        "date_filed": date_filed,
        "date_terminated": date_terminated,
        "source": "CourtListener",
        "source_url": _build_docket_url(docket_id),
    }


def _classify_case_type(cause: str, nos: str) -> str:
    text = (cause + " " + nos).lower()
    if "freedom of information" in text or "foia" in text:
        return "FOIA"
    if "administrative procedure" in text or "apa" in text:
        return "APA"
    if "habeas" in text:
        return "Habeas Corpus"
    if "mandamus" in text:
        return "Mandamus"
    if "civil rights" in text:
        return "Civil Rights"
    if "first amendment" in text:
        return "First Amendment"
    if "immigration" in text or "deportation" in text or "removal" in text:
        return "Immigration"
    if "employment" in text or "termination" in text:
        return "Employment"
    return "Federal Litigation"


def _org_flags(case_name: str, plaintiff: str, defendant: str) -> dict:
    """Return which key organisations appear in this case's parties."""
    text = f"{case_name} {plaintiff} {defendant}".lower()
    flags = {
        "involves_democracy_forward": False,
        "involves_aclu": False,
        "involves_democracy_defenders": False,
        "involves_public_citizen": False,
        "involves_protect_democracy": False,
        "names_federal_defendant": False,
    }
    for term in ORG_QUERIES["Democracy Forward"]:
        if term.lower() in text:
            flags["involves_democracy_forward"] = True
            break
    for term in ORG_QUERIES["ACLU"]:
        if term.lower() in text:
            flags["involves_aclu"] = True
            break
    for term in ORG_QUERIES["Democracy Defenders Fund"]:
        if term.lower() in text:
            flags["involves_democracy_defenders"] = True
            break
    for term in ORG_QUERIES["Public Citizen"]:
        if term.lower() in text:
            flags["involves_public_citizen"] = True
            break
    for term in ORG_QUERIES["Protect Democracy"]:
        if term.lower() in text:
            flags["involves_protect_democracy"] = True
            break
    for term in FEDERAL_DEFENDANT_TERMS:
        if term.lower() in text:
            flags["names_federal_defendant"] = True
            break
    return flags


def _search_dockets(query: str, page_size: int = 50, api_token: Optional[str] = None) -> list:
    """Search CourtListener dockets endpoint and return raw items."""
    params = {
        "q": query,
        "type": "r",        # RECAP / PACER dockets
        "order_by": "score desc",
        "page_size": page_size,
    }
    results = []
    url = f"{COURTLISTENER_BASE}/dockets/"
    try:
        data = _get(url, params, api_token)
        results.extend(data.get("results", []))
        # Fetch second page if available to widen coverage
        if data.get("next"):
            time.sleep(0.5)
            data2 = _get(data["next"], {}, api_token)
            results.extend(data2.get("results", []))
    except Exception as exc:
        logger.error("CourtListener docket search failed for '%s': %s", query, exc)
    return results


def fetch_priority_org_cases(api_token: Optional[str] = None) -> list:
    """
    Fetch cases from CourtListener filed by the five priority organisations.
    Returns a list of normalised case dicts.
    """
    seen_ids = set()
    cases = []

    for org_name, terms in ORG_QUERIES.items():
        for term in terms:
            logger.info("Fetching CourtListener cases for org: %s (%s)", org_name, term)
            items = _search_dockets(term, api_token=api_token)
            for item in items:
                docket_id = str(item.get("id", ""))
                if docket_id in seen_ids:
                    continue
                seen_ids.add(docket_id)
                parsed = _parse_docket(item)
                flags = _org_flags(
                    parsed["case_name"],
                    parsed["plaintiff"],
                    parsed["defendant"],
                )
                # Only include if it actually names a federal defendant
                if not flags["names_federal_defendant"]:
                    # Still include if the org is a clear plaintiff
                    if not flags.get(f"involves_{org_name.lower().replace(' ', '_').replace('-', '_')}"):
                        pass  # include anyway — org search already filters
                parsed.update(flags)
                cases.append(parsed)
            time.sleep(0.3)   # polite rate-limit

    return cases


def fetch_federal_defendant_cases(
    api_token: Optional[str] = None,
    since_date: Optional[date] = None,
) -> list:
    """
    Fetch recent federal cases naming Trump administration defendants.
    Optionally filters to cases filed on or after `since_date`.
    """
    seen_ids = set()
    cases = []

    # High-value targeted searches
    priority_queries = [
        "Trump v.",
        "v. Trump",
        "v. United States",
        "v. Department of Justice",
        "v. Department of Homeland Security",
        "DOGE",
        "Department of Government Efficiency",
        "FOIA federal",
        "Administrative Procedure Act federal agency",
        "habeas corpus immigration",
        "Alien Enemies Act",
        "reinstatement federal employee",
    ]

    if since_date:
        date_str = since_date.isoformat()
        priority_queries = [f"{q} date_filed:[{date_str} TO *]" for q in priority_queries]

    for query in priority_queries:
        logger.info("Fetching CourtListener federal-defendant cases: %s", query)
        items = _search_dockets(query, api_token=api_token)
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            flags = _org_flags(
                parsed["case_name"],
                parsed["plaintiff"],
                parsed["defendant"],
            )
            parsed.update(flags)
            # Only include if federal defendant is present
            if flags["names_federal_defendant"]:
                cases.append(parsed)
        time.sleep(0.3)

    return cases


def fetch_case_type_cases(api_token: Optional[str] = None) -> list:
    """
    Fetch cases by relevant cause-of-action keywords (FOIA, APA, habeas, etc.)
    against federal defendants.
    """
    seen_ids = set()
    cases = []

    for query in CASE_TYPE_QUERIES:
        full_query = f"{query} federal"
        logger.info("Fetching CourtListener case-type cases: %s", full_query)
        items = _search_dockets(full_query, api_token=api_token)
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            flags = _org_flags(
                parsed["case_name"],
                parsed["plaintiff"],
                parsed["defendant"],
            )
            parsed.update(flags)
            if flags["names_federal_defendant"]:
                cases.append(parsed)
        time.sleep(0.3)

    return cases


def fetch_all(api_token: Optional[str] = None, since_date: Optional[date] = None) -> list:
    """
    Master fetch — runs all three query strategies and deduplicates by docket_id.
    Returns a combined, deduplicated list of normalised case dicts.
    """
    all_cases = []
    seen = set()

    for batch in [
        fetch_priority_org_cases(api_token),
        fetch_federal_defendant_cases(api_token, since_date),
        fetch_case_type_cases(api_token),
    ]:
        for case in batch:
            key = case.get("docket_id") or case.get("case_number") or case["case_name"]
            if key not in seen:
                seen.add(key)
                all_cases.append(case)

    logger.info("CourtListener: fetched %d unique cases", len(all_cases))
    return all_cases

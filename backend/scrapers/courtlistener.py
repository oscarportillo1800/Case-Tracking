"""
CourtListener API scraper — primary data source.

CourtListener provides free, vetted federal court data via its REST API.
API docs: https://www.courtlistener.com/api/rest/v4/

This module queries CourtListener for:
  - Federal litigation against the Trump administration / named federal defendants
  - Cases filed by Democracy Forward, ACLU, Democracy Defenders Fund,
    Public Citizen, and Protect Democracy
  - FOIA, APA, habeas, tariff, and related federal case types
  - Cases in U.S. District Courts, Circuit Courts, the Supreme Court,
    the U.S. Court of Federal Claims (CoFC), and the U.S. Court of
    International Trade (CIT)

DATE FLOOR: Only cases filed on or after 2025-01-20 (Trump's second inauguration)
are returned.
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

# Hard date floor — second Trump term begins January 20, 2025
DATE_FLOOR = "2025-01-20"
DATE_FLOOR_DATE = date(2025, 1, 20)

# CourtListener court codes for special courts
COFC_COURT_CODE = "uscfc"   # U.S. Court of Federal Claims
CIT_COURT_CODE = "cit"      # U.S. Court of International Trade

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
    "U.S. International Trade Commission",
    "Office of the United States Trade Representative",
    "USTR",
]

# ── Case-type keyword queries ──────────────────────────────────────────────────
CASE_TYPE_QUERIES = [
    # Civil liberties / government accountability
    "Freedom of Information Act federal",
    "Administrative Procedure Act federal agency",
    "habeas corpus immigration",
    "mandamus federal",
    "preliminary injunction federal agency",
    "temporary restraining order federal agency",
    "First Amendment federal",
    "Fifth Amendment due process federal",
    "unlawful termination federal employee",
    "reinstatement federal employee",
    "DOGE",
    "Alien Enemies Act",
    # Tariff / trade
    "IEEPA tariff",
    "International Emergency Economic Powers Act tariff",
    "Section 232 tariff",
    "Section 301 tariff",
    "Section 201 tariff",
    "tariff executive order challenge",
    "trade war tariff lawsuit",
    "reciprocal tariff",
    "steel tariff aluminum tariff",
]

# ── Tariff / trade specific queries (Court of International Trade + CoFC) ─────
TARIFF_QUERIES = [
    "IEEPA",
    "International Emergency Economic Powers Act",
    "tariff unconstitutional",
    "Section 232",
    "Section 301",
    "reciprocal tariff",
    "trade remedy",
    "customs duty challenge",
    "steel tariff",
    "aluminum tariff",
    "solar tariff",
    "China tariff",
]


def _headers(api_token: Optional[str] = None) -> dict:
    h = {"Accept": "application/json"}
    token = api_token or os.getenv("COURTLISTENER_API_TOKEN")
    if token:
        h["Authorization"] = f"Token {token}"
    return h


def _get(url: str, params: dict, api_token: Optional[str] = None) -> dict:
    """GET with simple retry/backoff."""
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
        return "District Court"
    c = court_str.lower()
    if "supreme" in c:
        return "Supreme Court"
    if any(x in c for x in ["circuit", "appeals", "appellate"]):
        return "Circuit Court"
    if "federal claims" in c or "claims court" in c or "cofc" in c:
        return "Court of Federal Claims"
    if "international trade" in c or " cit " in c:
        return "Court of International Trade"
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

    # Enforce date floor — skip cases before Trump's second term
    if date_filed and date_filed < DATE_FLOOR_DATE:
        return {}

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
        # Complaint fields populated later by fetch_complaint_docs()
        "complaint_url": None,
        "complaint_pdf_url": None,
    }


def _classify_case_type(cause: str, nos: str) -> str:
    text = (cause + " " + nos).lower()
    if "freedom of information" in text or "foia" in text:
        return "FOIA"
    if "administrative procedure" in text or " apa " in text:
        return "APA"
    if "habeas" in text:
        return "Habeas Corpus"
    if "mandamus" in text:
        return "Mandamus"
    if any(x in text for x in [
        "tariff", "ieepa", "international emergency economic powers",
        "section 232", "section 301", "section 201", "customs duty",
        "trade remedy", "reciprocal tariff",
    ]):
        return "Tariff / Trade"
    if "civil rights" in text:
        return "Civil Rights"
    if "first amendment" in text:
        return "First Amendment"
    if "immigration" in text or "deportation" in text or "removal" in text:
        return "Immigration"
    if "employment" in text or "termination" in text:
        return "Employment"
    if "due process" in text:
        return "Due Process"
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


def _search_dockets(
    query: str,
    page_size: int = 50,
    api_token: Optional[str] = None,
    extra_params: Optional[dict] = None,
) -> list:
    """Search CourtListener dockets and return raw items."""
    params = {
        "q": query,
        "type": "r",        # RECAP/PACER dockets
        "order_by": "score desc",
        "page_size": page_size,
        "filed_after": DATE_FLOOR,   # Hard date floor
    }
    if extra_params:
        params.update(extra_params)

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


# ── Complaint document fetching ────────────────────────────────────────────────

def fetch_complaint_docs(docket_id: str, api_token: Optional[str] = None) -> dict:
    """
    Attempt to retrieve the complaint document URL and direct PDF link for
    a given CourtListener docket.

    Strategy:
      1. Fetch the first 3 docket entries for the docket (entry_number=1 is
         typically the complaint).
      2. For each entry, inspect its recap_documents list.
      3. Prefer a document described as "Complaint" or "complaint"; fall back
         to the first available document in entry #1.
      4. Return {"complaint_url": ..., "complaint_pdf_url": ...}

    Returns empty dict if no documents are available.
    """
    url = f"{COURTLISTENER_BASE}/docket-entries/"
    params = {
        "docket": docket_id,
        "order_by": "entry_number",
        "page_size": 5,
    }
    try:
        data = _get(url, params, api_token)
    except Exception as exc:
        logger.debug("Could not fetch docket entries for %s: %s", docket_id, exc)
        return {}

    entries = data.get("results", [])
    if not entries:
        return {}

    def _score_doc(desc: str) -> int:
        """Higher score = more likely to be the complaint."""
        d = (desc or "").lower()
        if "complaint" in d:
            return 3
        if "petition" in d:
            return 2
        if "class action" in d:
            return 2
        if "filing" in d or "initial" in d:
            return 1
        return 0

    best_doc_url = None
    best_pdf_url = None
    best_score = -1

    for entry in entries[:3]:  # Only look at first 3 entries
        recap_docs = entry.get("recap_documents") or []
        for doc in recap_docs:
            desc = doc.get("description", "")
            score = _score_doc(desc)
            if score > best_score:
                best_score = score
                # CourtListener document page URL
                abs_url = doc.get("absolute_url", "")
                best_doc_url = f"{COURTLISTENER_BASE_URL}{abs_url}" if abs_url else None
                # Direct PDF path (CourtListener RECAP storage)
                fp = doc.get("filepath_local", "")
                if fp:
                    best_pdf_url = f"https://storage.courtlistener.com/recap/{fp}"

    result = {}
    if best_doc_url:
        result["complaint_url"] = best_doc_url
    if best_pdf_url:
        result["complaint_pdf_url"] = best_pdf_url
    return result


# ── Fetch functions ────────────────────────────────────────────────────────────

def fetch_priority_org_cases(api_token: Optional[str] = None) -> list:
    """Fetch cases filed by the five priority organisations."""
    seen_ids: set = set()
    cases = []

    for org_name, terms in ORG_QUERIES.items():
        for term in terms:
            logger.info("CL org search: %s (%s)", org_name, term)
            items = _search_dockets(term, api_token=api_token)
            for item in items:
                docket_id = str(item.get("id", ""))
                if docket_id in seen_ids:
                    continue
                seen_ids.add(docket_id)
                parsed = _parse_docket(item)
                if not parsed:   # filtered out by date floor
                    continue
                flags = _org_flags(parsed["case_name"], parsed["plaintiff"], parsed["defendant"])
                parsed.update(flags)
                cases.append(parsed)
            time.sleep(0.3)

    return cases


def fetch_federal_defendant_cases(api_token: Optional[str] = None) -> list:
    """Fetch cases naming Trump administration defendants filed since Jan 20 2025."""
    seen_ids: set = set()
    cases = []

    priority_queries = [
        "Trump v.",
        "v. Trump",
        "v. United States",
        "v. Department of Justice",
        "v. Department of Homeland Security",
        "v. Department of Education",
        "v. Department of Defense",
        "DOGE federal",
        "Department of Government Efficiency",
        "FOIA federal 2025",
        "Administrative Procedure Act federal agency 2025",
        "habeas corpus immigration 2025",
        "Alien Enemies Act",
        "reinstatement federal employee 2025",
        "federal worker termination injunction",
    ]

    for query in priority_queries:
        logger.info("CL federal-defendant search: %s", query)
        items = _search_dockets(query, api_token=api_token)
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            if not parsed:
                continue
            flags = _org_flags(parsed["case_name"], parsed["plaintiff"], parsed["defendant"])
            parsed.update(flags)
            if flags["names_federal_defendant"]:
                cases.append(parsed)
        time.sleep(0.3)

    return cases


def fetch_tariff_cases(api_token: Optional[str] = None) -> list:
    """
    Fetch tariff and trade challenge cases.
    Searches both general federal dockets and the Court of International Trade
    (CIT) and Court of Federal Claims (CoFC) specifically.
    """
    seen_ids: set = set()
    cases = []

    for query in TARIFF_QUERIES:
        logger.info("CL tariff search: %s", query)
        items = _search_dockets(query, api_token=api_token)
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            if not parsed:
                continue
            flags = _org_flags(parsed["case_name"], parsed["plaintiff"], parsed["defendant"])
            parsed.update(flags)
            # For tariff cases we include even if no individual federal defendant
            # keyword matched — the case type classification handles it
            if parsed["case_type"] == "Tariff / Trade" or flags["names_federal_defendant"]:
                # Ensure tariff type is set correctly
                if parsed["case_type"] != "Tariff / Trade":
                    parsed["case_type"] = "Tariff / Trade"
                cases.append(parsed)
        time.sleep(0.3)

    # Also query CoFC and CIT directly by court
    for court_code, label in [(COFC_COURT_CODE, "CoFC"), (CIT_COURT_CODE, "CIT")]:
        logger.info("CL court-specific search: %s", label)
        items = _search_dockets(
            "tariff OR IEEPA OR trade",
            api_token=api_token,
            extra_params={"court": court_code},
        )
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            if not parsed:
                continue
            flags = _org_flags(parsed["case_name"], parsed["plaintiff"], parsed["defendant"])
            parsed.update(flags)
            if parsed["case_type"] not in ("Tariff / Trade",):
                parsed["case_type"] = "Tariff / Trade"
            cases.append(parsed)
        time.sleep(0.3)

    return cases


def fetch_case_type_cases(api_token: Optional[str] = None) -> list:
    """Fetch cases by cause-of-action keywords against federal defendants."""
    seen_ids: set = set()
    cases = []

    for query in CASE_TYPE_QUERIES:
        logger.info("CL case-type search: %s", query)
        items = _search_dockets(query, api_token=api_token)
        for item in items:
            docket_id = str(item.get("id", ""))
            if docket_id in seen_ids:
                continue
            seen_ids.add(docket_id)
            parsed = _parse_docket(item)
            if not parsed:
                continue
            flags = _org_flags(parsed["case_name"], parsed["plaintiff"], parsed["defendant"])
            parsed.update(flags)
            if flags["names_federal_defendant"] or parsed["case_type"] == "Tariff / Trade":
                cases.append(parsed)
        time.sleep(0.3)

    return cases


def enrich_with_complaint_docs(cases: list, api_token: Optional[str] = None) -> list:
    """
    For each case that has a docket_id and no complaint_url yet, attempt to
    fetch the complaint document from CourtListener docket entries.

    This makes one additional API call per case, so it is rate-limited.
    Only runs when an API token is present (unauthenticated requests hit strict
    rate limits quickly).
    """
    token = api_token or os.getenv("COURTLISTENER_API_TOKEN")
    if not token:
        logger.info(
            "Skipping complaint doc enrichment — no API token "
            "(set COURTLISTENER_API_TOKEN to enable)"
        )
        return cases

    enriched = 0
    for case in cases:
        docket_id = case.get("docket_id")
        if not docket_id or case.get("complaint_url"):
            continue
        try:
            docs = fetch_complaint_docs(docket_id, token)
            if docs:
                case.update(docs)
                enriched += 1
        except Exception as exc:
            logger.debug("Complaint doc fetch failed for docket %s: %s", docket_id, exc)
        time.sleep(0.25)   # polite rate limit

    logger.info("Complaint doc enrichment: %d/%d cases enriched", enriched, len(cases))
    return cases


def fetch_all(api_token: Optional[str] = None) -> list:
    """
    Master fetch — runs all query strategies, deduplicates by docket_id,
    enforces the Jan 20 2025 date floor, then enriches with complaint docs.
    Returns a combined, deduplicated list of normalised case dicts.
    """
    all_cases = []
    seen: set = set()

    for batch in [
        fetch_priority_org_cases(api_token),
        fetch_federal_defendant_cases(api_token),
        fetch_tariff_cases(api_token),
        fetch_case_type_cases(api_token),
    ]:
        for case in batch:
            key = case.get("docket_id") or case.get("case_number") or case["case_name"]
            if key not in seen:
                seen.add(key)
                all_cases.append(case)

    logger.info("CourtListener: %d unique cases before complaint enrichment", len(all_cases))

    # Enrich with complaint documents (requires API token)
    all_cases = enrich_with_complaint_docs(all_cases, api_token)

    logger.info("CourtListener: %d unique cases total", len(all_cases))
    return all_cases

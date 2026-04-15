"""
Sync engine — ingests cases from all sources into the database.

Called by the scheduler (daily) or manually via the /api/sync endpoint.
Each run is logged to the SyncLog table for full auditability.
"""

import logging
from datetime import datetime, date

from models import db, Case, SyncLog
from scrapers import courtlistener, just_security, michigan_clearinghouse

logger = logging.getLogger(__name__)


def _upsert_case(app, case_data: dict) -> tuple:
    """
    Insert a new case or update an existing one (matched on docket_id or
    case_number+court combination).  Returns (was_added: bool, was_updated: bool).
    """
    with app.app_context():
        existing = None

        # Prefer matching on CourtListener docket_id (most stable key)
        if case_data.get("docket_id"):
            existing = Case.query.filter_by(
                docket_id=case_data["docket_id"]
            ).first()

        # Fall back to case_number + court
        if not existing and case_data.get("case_number") and case_data.get("court"):
            existing = Case.query.filter_by(
                case_number=case_data["case_number"],
                court=case_data["court"],
            ).first()

        if existing:
            # Update mutable fields but never overwrite user-curated hidden/hidden_reason
            changed = False
            for field in [
                "case_name", "court", "court_level", "docket_url", "case_type",
                "cause_of_action", "nature_of_suit", "plaintiff", "defendant",
                "date_filed", "date_terminated", "source_url",
                "involves_democracy_forward", "involves_aclu",
                "involves_democracy_defenders", "involves_public_citizen",
                "involves_protect_democracy", "names_federal_defendant",
            ]:
                new_val = case_data.get(field)
                if new_val is not None and getattr(existing, field) != new_val:
                    setattr(existing, field, new_val)
                    changed = True
            if changed:
                existing.updated_at = datetime.utcnow()
                db.session.commit()
                return False, True
            return False, False

        # New case
        new_case = Case(
            case_name=case_data["case_name"],
            case_number=case_data.get("case_number"),
            court=case_data.get("court"),
            court_level=case_data.get("court_level"),
            docket_url=case_data.get("docket_url"),
            docket_id=case_data.get("docket_id"),
            case_type=case_data.get("case_type", "Federal Litigation"),
            cause_of_action=case_data.get("cause_of_action"),
            nature_of_suit=case_data.get("nature_of_suit"),
            plaintiff=case_data.get("plaintiff"),
            defendant=case_data.get("defendant"),
            date_filed=case_data.get("date_filed"),
            date_terminated=case_data.get("date_terminated"),
            source=case_data.get("source", "Unknown"),
            source_url=case_data.get("source_url"),
            involves_democracy_forward=case_data.get("involves_democracy_forward", False),
            involves_aclu=case_data.get("involves_aclu", False),
            involves_democracy_defenders=case_data.get("involves_democracy_defenders", False),
            involves_public_citizen=case_data.get("involves_public_citizen", False),
            involves_protect_democracy=case_data.get("involves_protect_democracy", False),
            names_federal_defendant=case_data.get("names_federal_defendant", False),
            hidden=False,
        )
        db.session.add(new_case)
        db.session.commit()
        return True, False


def run_sync(app, source_filter: str = "all", courtlistener_token: str = None) -> dict:
    """
    Main sync entry point.  `source_filter` can be "all", "courtlistener",
    "just_security", or "michigan_clearinghouse".

    Returns a summary dict with counts per source.
    """
    summary = {}

    sources = {
        "courtlistener": _sync_courtlistener,
        "just_security": _sync_just_security,
        "michigan_clearinghouse": _sync_michigan_clearinghouse,
    }

    if source_filter != "all" and source_filter in sources:
        targets = {source_filter: sources[source_filter]}
    else:
        targets = sources

    for src_name, sync_fn in targets.items():
        log = SyncLog(source=src_name, status="running")
        with app.app_context():
            db.session.add(log)
            db.session.commit()
            log_id = log.id

        added = updated = fetched = 0
        error_msg = None
        try:
            if src_name == "courtlistener":
                cases = sync_fn(courtlistener_token)
            else:
                cases = sync_fn()

            fetched = len(cases)
            for case_data in cases:
                was_added, was_updated = _upsert_case(app, case_data)
                if was_added:
                    added += 1
                elif was_updated:
                    updated += 1

            status = "success"
        except Exception as exc:
            error_msg = str(exc)
            status = "error"
            logger.exception("Sync failed for source %s", src_name)

        with app.app_context():
            log = SyncLog.query.get(log_id)
            if log:
                log.finished_at = datetime.utcnow()
                log.cases_fetched = fetched
                log.cases_added = added
                log.cases_updated = updated
                log.status = status
                log.error_message = error_msg
                db.session.commit()

        summary[src_name] = {
            "fetched": fetched,
            "added": added,
            "updated": updated,
            "status": status,
            "error": error_msg,
        }
        logger.info(
            "Sync %s: fetched=%d added=%d updated=%d status=%s",
            src_name, fetched, added, updated, status,
        )

    return summary


def _sync_courtlistener(token=None) -> list:
    return courtlistener.fetch_all(api_token=token)


def _sync_just_security() -> list:
    return just_security.fetch_all()


def _sync_michigan_clearinghouse() -> list:
    return michigan_clearinghouse.fetch_all()

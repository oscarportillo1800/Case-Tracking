"""
Database models for the Federal Litigation Tracker.
"""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Case(db.Model):
    __tablename__ = "cases"

    id = db.Column(db.Integer, primary_key=True)

    # Core identifiers
    case_name = db.Column(db.String(500), nullable=False)
    case_number = db.Column(db.String(100), nullable=True)
    court = db.Column(db.String(200), nullable=True)
    court_level = db.Column(db.String(50), nullable=True)   # "District", "Circuit", "Supreme"

    # Docket information
    docket_url = db.Column(db.String(500), nullable=True)
    docket_id = db.Column(db.String(100), nullable=True)    # CourtListener docket ID

    # Case classification
    case_type = db.Column(db.String(100), nullable=True)    # FOIA, APA, Habeas, etc.
    cause_of_action = db.Column(db.String(300), nullable=True)
    nature_of_suit = db.Column(db.String(200), nullable=True)

    # Parties
    plaintiff = db.Column(db.String(500), nullable=True)
    defendant = db.Column(db.String(500), nullable=True)

    # Key organization flags (for priority filtering)
    involves_democracy_forward = db.Column(db.Boolean, default=False)
    involves_aclu = db.Column(db.Boolean, default=False)
    involves_democracy_defenders = db.Column(db.Boolean, default=False)
    involves_public_citizen = db.Column(db.Boolean, default=False)
    involves_protect_democracy = db.Column(db.Boolean, default=False)

    # Against-Trump-administration flag
    names_federal_defendant = db.Column(db.Boolean, default=False)

    # Dates
    date_filed = db.Column(db.Date, nullable=True)
    date_terminated = db.Column(db.Date, nullable=True)

    # Source tracking
    source = db.Column(db.String(100), nullable=False)      # "CourtListener", "JustSecurity", etc.
    source_url = db.Column(db.String(500), nullable=True)   # Direct link to source entry

    # User curation — hidden cases are excluded from default view but remain in DB
    # permanently deleted cases are removed entirely via the DELETE endpoint
    hidden = db.Column(db.Boolean, default=False, nullable=False)
    hidden_at = db.Column(db.DateTime, nullable=True)
    hidden_reason = db.Column(db.String(300), nullable=True)

    # Internal metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "case_name": self.case_name,
            "case_number": self.case_number,
            "court": self.court,
            "court_level": self.court_level,
            "docket_url": self.docket_url,
            "docket_id": self.docket_id,
            "case_type": self.case_type,
            "cause_of_action": self.cause_of_action,
            "nature_of_suit": self.nature_of_suit,
            "plaintiff": self.plaintiff,
            "defendant": self.defendant,
            "involves_democracy_forward": self.involves_democracy_forward,
            "involves_aclu": self.involves_aclu,
            "involves_democracy_defenders": self.involves_democracy_defenders,
            "involves_public_citizen": self.involves_public_citizen,
            "involves_protect_democracy": self.involves_protect_democracy,
            "names_federal_defendant": self.names_federal_defendant,
            "date_filed": self.date_filed.isoformat() if self.date_filed else None,
            "date_terminated": self.date_terminated.isoformat() if self.date_terminated else None,
            "source": self.source,
            "source_url": self.source_url,
            "hidden": self.hidden,
            "hidden_at": self.hidden_at.isoformat() if self.hidden_at else None,
            "hidden_reason": self.hidden_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SyncLog(db.Model):
    """Tracks each automated sync run for auditing and debugging."""
    __tablename__ = "sync_logs"

    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(100), nullable=False)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    cases_fetched = db.Column(db.Integer, default=0)
    cases_added = db.Column(db.Integer, default=0)
    cases_updated = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="running")    # running | success | error
    error_message = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "source": self.source,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "cases_fetched": self.cases_fetched,
            "cases_added": self.cases_added,
            "cases_updated": self.cases_updated,
            "status": self.status,
            "error_message": self.error_message,
        }

"""
Federal Litigation Tracker — Flask backend.

Endpoints
─────────
GET  /api/cases             List cases (filterable, paginated)
GET  /api/cases/<id>        Get a single case
PATCH /api/cases/<id>/hide  Soft-hide a case (keeps it in DB, removes from default view)
PATCH /api/cases/<id>/unhide Restore a hidden case
DELETE /api/cases/<id>      Permanently delete a case
GET  /api/cases/hidden      List all user-hidden cases
GET  /api/stats             Dashboard statistics
GET  /api/sync_logs         Recent sync history
POST /api/sync              Trigger a manual sync
GET  /api/health            Health check
"""

import logging
import os
from datetime import datetime

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

from models import db, Case, SyncLog
import scheduler as sched

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App factory ───────────────────────────────────────────────────────────────

def create_app():
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "..", "frontend"),
        static_url_path="",
    )

    # Config
    db_path = os.path.join(os.path.dirname(__file__), "litigation.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", os.urandom(32).hex())
    app.config["JSON_SORT_KEYS"] = False

    CORS(app, resources={r"/api/*": {"origins": "*"}})
    db.init_app(app)

    with app.app_context():
        db.create_all()

    # ── Serve frontend ─────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    # ── Health check ───────────────────────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})

    # ── GET /api/cases ─────────────────────────────────────────────────────────
    @app.route("/api/cases")
    def list_cases():
        """
        Query parameters:
          page          int (default 1)
          per_page      int (default 50, max 200)
          search        str — free-text search on case name, plaintiff, defendant
          court_level   str — "District Court"|"Circuit Court"|"Supreme Court"
          court         str — partial court name match
          case_type     str — FOIA|APA|Habeas Corpus|...
          source        str — CourtListener|Just Security|Michigan Clearinghouse
          org           str — democracy_forward|aclu|democracy_defenders|
                               public_citizen|protect_democracy
          federal_only  bool (default true) — only names_federal_defendant=True
          date_from     YYYY-MM-DD
          date_to       YYYY-MM-DD
          show_hidden   bool (default false) — include hidden cases
          sort          str — date_filed|case_name|court (default date_filed)
          order         str — desc|asc (default desc)
        """
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(200, max(1, int(request.args.get("per_page", 50))))
        search = request.args.get("search", "").strip()
        court_level = request.args.get("court_level", "").strip()
        court = request.args.get("court", "").strip()
        case_type = request.args.get("case_type", "").strip()
        source = request.args.get("source", "").strip()
        org = request.args.get("org", "").strip()
        federal_only = request.args.get("federal_only", "true").lower() == "true"
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()
        show_hidden = request.args.get("show_hidden", "false").lower() == "true"
        sort_field = request.args.get("sort", "date_filed")
        order = request.args.get("order", "desc")

        q = Case.query

        # Hidden filter
        if not show_hidden:
            q = q.filter(Case.hidden == False)  # noqa: E712

        # Free-text search
        if search:
            like = f"%{search}%"
            q = q.filter(
                db.or_(
                    Case.case_name.ilike(like),
                    Case.plaintiff.ilike(like),
                    Case.defendant.ilike(like),
                    Case.case_number.ilike(like),
                    Case.court.ilike(like),
                )
            )

        if court_level:
            q = q.filter(Case.court_level == court_level)

        if court:
            q = q.filter(Case.court.ilike(f"%{court}%"))

        if case_type:
            q = q.filter(Case.case_type == case_type)

        if source:
            q = q.filter(Case.source == source)

        if federal_only:
            q = q.filter(Case.names_federal_defendant == True)  # noqa: E712

        if org:
            org_map = {
                "democracy_forward": Case.involves_democracy_forward,
                "aclu": Case.involves_aclu,
                "democracy_defenders": Case.involves_democracy_defenders,
                "public_citizen": Case.involves_public_citizen,
                "protect_democracy": Case.involves_protect_democracy,
            }
            if org in org_map:
                q = q.filter(org_map[org] == True)  # noqa: E712

        if date_from:
            try:
                q = q.filter(Case.date_filed >= datetime.strptime(date_from, "%Y-%m-%d").date())
            except ValueError:
                pass
        if date_to:
            try:
                q = q.filter(Case.date_filed <= datetime.strptime(date_to, "%Y-%m-%d").date())
            except ValueError:
                pass

        # Sorting
        sort_col_map = {
            "date_filed": Case.date_filed,
            "case_name": Case.case_name,
            "court": Case.court,
            "created_at": Case.created_at,
        }
        sort_col = sort_col_map.get(sort_field, Case.date_filed)
        if order == "asc":
            q = q.order_by(sort_col.asc().nullslast())
        else:
            q = q.order_by(sort_col.desc().nullslast())

        total = q.count()
        cases = q.offset((page - 1) * per_page).limit(per_page).all()

        return jsonify({
            "cases": [c.to_dict() for c in cases],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
        })

    # ── GET /api/cases/<id> ────────────────────────────────────────────────────
    @app.route("/api/cases/<int:case_id>")
    def get_case(case_id):
        case = Case.query.get_or_404(case_id)
        return jsonify(case.to_dict())

    # ── GET /api/cases/hidden ──────────────────────────────────────────────────
    @app.route("/api/cases/hidden")
    def list_hidden_cases():
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(200, max(1, int(request.args.get("per_page", 50))))
        q = Case.query.filter(Case.hidden == True).order_by(Case.hidden_at.desc())  # noqa: E712
        total = q.count()
        cases = q.offset((page - 1) * per_page).limit(per_page).all()
        return jsonify({
            "cases": [c.to_dict() for c in cases],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": max(1, (total + per_page - 1) // per_page),
            },
        })

    # ── PATCH /api/cases/<id>/hide ─────────────────────────────────────────────
    @app.route("/api/cases/<int:case_id>/hide", methods=["PATCH"])
    def hide_case(case_id):
        """
        Soft-hide a case.  It stays in the database and can be restored via
        /unhide.  Accepts an optional JSON body: {"reason": "not relevant"}.
        """
        case = Case.query.get_or_404(case_id)
        body = request.get_json(silent=True) or {}
        reason = str(body.get("reason", ""))[:299] if body.get("reason") else None

        case.hidden = True
        case.hidden_at = datetime.utcnow()
        case.hidden_reason = reason
        db.session.commit()
        return jsonify({"message": "Case hidden", "id": case_id})

    # ── PATCH /api/cases/<id>/unhide ───────────────────────────────────────────
    @app.route("/api/cases/<int:case_id>/unhide", methods=["PATCH"])
    def unhide_case(case_id):
        """Restore a previously hidden case to the active tracker view."""
        case = Case.query.get_or_404(case_id)
        case.hidden = False
        case.hidden_at = None
        case.hidden_reason = None
        db.session.commit()
        return jsonify({"message": "Case restored", "id": case_id})

    # ── DELETE /api/cases/<id> ─────────────────────────────────────────────────
    @app.route("/api/cases/<int:case_id>", methods=["DELETE"])
    def delete_case(case_id):
        """
        Permanently remove a case from the database.
        This action is irreversible.  The case will be re-imported on the next
        sync unless it is excluded by the scraper logic.
        """
        case = Case.query.get_or_404(case_id)
        db.session.delete(case)
        db.session.commit()
        return jsonify({"message": "Case permanently deleted", "id": case_id})

    # ── GET /api/stats ─────────────────────────────────────────────────────────
    @app.route("/api/stats")
    def stats():
        total = Case.query.filter(Case.hidden == False).count()  # noqa: E712
        hidden_count = Case.query.filter(Case.hidden == True).count()  # noqa: E712

        by_source = db.session.query(Case.source, db.func.count(Case.id)).filter(
            Case.hidden == False  # noqa: E712
        ).group_by(Case.source).all()

        by_court_level = db.session.query(Case.court_level, db.func.count(Case.id)).filter(
            Case.hidden == False  # noqa: E712
        ).group_by(Case.court_level).all()

        by_case_type = db.session.query(Case.case_type, db.func.count(Case.id)).filter(
            Case.hidden == False  # noqa: E712
        ).group_by(Case.case_type).order_by(db.func.count(Case.id).desc()).all()

        # Priority org counts
        org_counts = {
            "democracy_forward": Case.query.filter(
                Case.involves_democracy_forward == True, Case.hidden == False  # noqa: E712
            ).count(),
            "aclu": Case.query.filter(
                Case.involves_aclu == True, Case.hidden == False  # noqa: E712
            ).count(),
            "democracy_defenders": Case.query.filter(
                Case.involves_democracy_defenders == True, Case.hidden == False  # noqa: E712
            ).count(),
            "public_citizen": Case.query.filter(
                Case.involves_public_citizen == True, Case.hidden == False  # noqa: E712
            ).count(),
            "protect_democracy": Case.query.filter(
                Case.involves_protect_democracy == True, Case.hidden == False  # noqa: E712
            ).count(),
        }

        last_sync = SyncLog.query.filter(
            SyncLog.status == "success"
        ).order_by(SyncLog.finished_at.desc()).first()

        return jsonify({
            "total_cases": total,
            "hidden_cases": hidden_count,
            "by_source": dict(by_source),
            "by_court_level": dict(by_court_level),
            "by_case_type": [{"type": t, "count": c} for t, c in by_case_type],
            "priority_orgs": org_counts,
            "last_sync": last_sync.finished_at.isoformat() if last_sync and last_sync.finished_at else None,
        })

    # ── GET /api/sync_logs ─────────────────────────────────────────────────────
    @app.route("/api/sync_logs")
    def sync_logs():
        logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(50).all()
        return jsonify([l.to_dict() for l in logs])

    # ── POST /api/sync ─────────────────────────────────────────────────────────
    @app.route("/api/sync", methods=["POST"])
    def trigger_sync():
        """
        Manually trigger a sync.  Accepts optional JSON body:
        {"source": "courtlistener"|"just_security"|"michigan_clearinghouse"|"all"}
        """
        body = request.get_json(silent=True) or {}
        source = body.get("source", "all")
        allowed = {"all", "courtlistener", "just_security", "michigan_clearinghouse"}
        if source not in allowed:
            return jsonify({"error": "Invalid source"}), 400

        from sync import run_sync
        token = os.getenv("COURTLISTENER_API_TOKEN")
        summary = run_sync(app, source_filter=source, courtlistener_token=token)
        return jsonify({"message": "Sync complete", "summary": summary})

    return app


# ── Entry point ────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    sched.start(app)
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    logger.info("Starting Federal Litigation Tracker on port %d", port)
    try:
        app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
    finally:
        sched.stop()

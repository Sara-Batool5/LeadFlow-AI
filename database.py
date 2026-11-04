
import os
import re
import uuid
from datetime import datetime

import psycopg2
from psycopg2.extras import RealDictCursor, Json


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_url():
    """Read the Neon connection string from Streamlit secrets or environment."""
    try:
        import streamlit as st
        database_url = st.secrets.get("NEON_DATABASE_URL")
        if database_url:
            return database_url
    except Exception:
        pass

    database_url = os.getenv("NEON_DATABASE_URL")
    if not database_url:
        raise ValueError(
            "NEON_DATABASE_URL is missing. Add it to Streamlit Cloud secrets."
        )

    return database_url


def _connect():
    """Create a secure connection to Neon PostgreSQL."""
    return psycopg2.connect(
        get_database_url(),
        sslmode="require",
        cursor_factory=RealDictCursor
    )


def test_connection():
    """Test whether the database is reachable."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS version;")
                result = cur.fetchone()
        return True, result["version"]
    except Exception as exc:
        return False, str(exc)


# ============================================================
# DATABASE INITIALIZATION
# IMPORTANT: Does not create or alter existing tables.
# ============================================================

def initialize_schema():
    """Create only helpful indexes on the existing tables."""
    statements = [
        """
        CREATE INDEX IF NOT EXISTS idx_leads_email
        ON leads (LOWER(email))
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leads_created_at
        ON leads (created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leads_status
        ON leads (status)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_events_lead_id
        ON workflow_events (lead_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_qualification_results_lead_id
        ON qualification_results (lead_id)
        """
    ]

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)
        return True, "Database indexes checked successfully."
    except Exception as exc:
        return False, str(exc)


def get_table_counts():
    """Return record counts for the main LeadFlow AI tables."""
    tables = [
        "leads",
        "workflow_events",
        "qualification_results",
        "sales_owners",
        "email_drafts"
    ]

    counts = {}

    with _connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                # Table names are fixed in this function, not user input.
                cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
                counts[table] = cur.fetchone()["total"]

    return counts


# ============================================================
# NORMALIZATION HELPERS
# ============================================================

def _clean(value):
    """Convert missing or whitespace-only values to None."""
    if value is None:
        return None

    value = str(value).strip()
    return value if value else None


def _normalize_email(value):
    value = _clean(value)
    return value.lower() if value else None


def _normalize_text(value):
    value = _clean(value)
    return re.sub(r"\s+", " ", value).lower() if value else None


def _normalize_website(value):
    value = _clean(value)

    if not value:
        return None

    value = value.lower()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)
    return value.rstrip("/")


def _get_lead_value(lead, *keys):
    """Read the first available value from alternate app/database field names."""
    for key in keys:
        value = lead.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _make_lead_reference():
    return "LF-" + datetime.now().strftime("%y%m%d") + "-" + uuid.uuid4().hex[:6].upper()


# ============================================================
# DUPLICATE DETECTION
# Strict matching avoids flagging different people at the same company.
# ============================================================

def find_potential_duplicates(lead):
    """
    Find likely duplicate leads using:
    1. Exact email match.
    2. Exact contact name + exact company.
    3. Exact contact name + exact website.

    A matching company or email domain alone is NOT sufficient.
    """
    email = _normalize_email(_get_lead_value(lead, "email"))
    contact_name = _normalize_text(
        _get_lead_value(lead, "contact_name", "full_name")
    )
    company = _normalize_text(_get_lead_value(lead, "company"))
    website = _normalize_website(_get_lead_value(lead, "website"))

    if not any([email, contact_name]):
        return []

    conditions = []
    params = []

    if email:
        conditions.append("LOWER(COALESCE(email, '')) = %s")
        params.append(email)

    if contact_name and company:
        conditions.append(
            """
            (
                LOWER(TRIM(COALESCE(full_name, ''))) = %s
                AND LOWER(TRIM(COALESCE(company, ''))) = %s
            )
            """
        )
        params.extend([contact_name, company])

    if contact_name and website:
        conditions.append(
            """
            (
                LOWER(TRIM(COALESCE(full_name, ''))) = %s
                AND LOWER(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(
                            LOWER(COALESCE(website, '')),
                            '^https?://', ''
                        ),
                        '^www\\.', ''
                    )
                ) = %s
            )
            """
        )
        params.extend([contact_name, website])

    if not conditions:
        return []

    sql = f"""
        SELECT
            id,
            lead_reference,
            full_name AS contact_name,
            email,
            company,
            website,
            job_title,
            industry,
            country,
            status,
            priority,
            created_at
        FROM leads
        WHERE {" OR ".join(conditions)}
        ORDER BY created_at DESC
        LIMIT 10
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


# ============================================================
# LEAD INTAKE
# ============================================================

def create_lead(lead):
    """
    Insert a lead into the existing BIGINT-based leads table.

    App fields are mapped to the actual database columns:
    contact_name -> full_name
    description  -> need_description
    budget       -> budget_range

    need_description is always non-NULL.
    Returns the newly created lead ID.
    """
    full_name = _clean(_get_lead_value(lead, "contact_name", "full_name"))
    email = _normalize_email(_get_lead_value(lead, "email"))

    if not full_name:
        raise ValueError("Contact name is required.")

    if not email:
        raise ValueError("Email address is required.")

    description = _clean(
        _get_lead_value(lead, "description", "need_description")
    ) or "Not provided"

    lead_reference = (
        _clean(lead.get("lead_reference")) or _make_lead_reference()
    )

    values = (
        lead_reference,
        full_name,
        email,
        _clean(lead.get("company")),
        _clean(lead.get("job_title")),
        _clean(lead.get("website")),
        _clean(lead.get("company_size")),
        _clean(lead.get("industry")),
        _clean(lead.get("country")),
        _clean(lead.get("source")) or "website_form",
        description,
        _clean(_get_lead_value(lead, "budget", "budget_range")),
        _clean(lead.get("timeline")),
        _clean(lead.get("status")) or "new",
        _clean(lead.get("priority")) or "unassessed",
        lead.get("assigned_owner_id"),
        lead.get("duplicate_of_lead_id"),
        bool(lead.get("consent_to_contact", False))
    )

    sql = """
        INSERT INTO leads (
            lead_reference,
            full_name,
            email,
            company,
            job_title,
            website,
            company_size,
            industry,
            country,
            source,
            need_description,
            budget_range,
            timeline,
            status,
            priority,
            assigned_owner_id,
            duplicate_of_lead_id,
            consent_to_contact
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, COALESCE(%s, 'Not provided'), %s, %s, %s,
            %s, %s, %s, %s
        )
        RETURNING id
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, values)
            result = cur.fetchone()

    return result["id"]


def get_leads(limit=500):
    """Return leads using app-friendly field names."""
    sql = """
        SELECT
            id,
            lead_reference,
            full_name AS contact_name,
            email,
            company,
            job_title,
            website,
            company_size,
            industry,
            country,
            source,
            need_description AS description,
            budget_range AS budget,
            timeline,
            status,
            priority,
            assigned_owner_id,
            duplicate_of_lead_id,
            consent_to_contact,
            created_at,
            updated_at
        FROM leads
        ORDER BY created_at DESC
        LIMIT %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [dict(row) for row in cur.fetchall()]


def get_lead_by_id(lead_id):
    """Get one lead by its BIGINT ID."""
    sql = """
        SELECT
            id,
            lead_reference,
            full_name AS contact_name,
            email,
            company,
            job_title,
            website,
            company_size,
            industry,
            country,
            source,
            need_description AS description,
            budget_range AS budget,
            timeline,
            status,
            priority,
            assigned_owner_id,
            duplicate_of_lead_id,
            consent_to_contact,
            created_at,
            updated_at
        FROM leads
        WHERE id = %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (lead_id,))
            result = cur.fetchone()

    return dict(result) if result else None


# ============================================================
# LEAD STATUS AND QUALIFICATION UPDATES
# ============================================================

def update_lead_status(lead_id, status):
    """Update a lead's status."""
    sql = """
        UPDATE leads
        SET status = %s,
            updated_at = NOW()
        WHERE id = %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (status, lead_id))
            return cur.rowcount > 0


def update_lead_qualification(
    lead_id,
    score=None,
    category=None,
    reasoning=None,
    priority=None
):
    """Update the qualification-related fields stored on the lead."""
    sql = """
        UPDATE leads
        SET
            priority = COALESCE(%s, priority),
            updated_at = NOW()
        WHERE id = %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (priority, lead_id))
            return cur.rowcount > 0


# ============================================================
# WORKFLOW EVENTS / AUDIT HISTORY
# ============================================================

def create_workflow_event(
    lead_id,
    event_type,
    event_status="completed",
    message=None,
    details=None,
    actor="LeadFlow AI"
):
    """Save a workflow or audit event."""
    sql = """
        INSERT INTO workflow_events (
            lead_id,
            event_type,
            event_status,
            message,
            details,
            actor
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    Json(details or {}),
                    actor
                )
            )
            result = cur.fetchone()

    return result["id"]


def get_workflow_events(limit=200):
    """Return recent workflow events with lead details."""
    sql = """
        SELECT
            we.id,
            we.lead_id,
            we.event_type,
            we.event_status,
            we.message,
            we.details,
            we.actor,
            we.created_at,
            l.lead_reference,
            l.full_name AS contact_name,
            l.company
        FROM workflow_events we
        LEFT JOIN leads l ON l.id = we.lead_id
        ORDER BY we.created_at DESC
        LIMIT %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [dict(row) for row in cur.fetchall()]


# ============================================================
# AI QUALIFICATION RESULTS
# ============================================================

def save_qualification_result(
    lead_id,
    score,
    category,
    reasoning,
    missing_information=None,
    recommended_next_action=None,
    human_review_required=False,
    model_name="Groq"
):
    """Save an AI qualification result."""
    sql = """
        INSERT INTO qualification_results (
            lead_id,
            model_name,
            score,
            category,
            reasoning,
            missing_information,
            recommended_next_action,
            human_review_required
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    lead_id,
                    model_name,
                    score,
                    category,
                    reasoning,
                    Json(missing_information or []),
                    recommended_next_action,
                    bool(human_review_required)
                )
            )
            result = cur.fetchone()

    return result["id"]


def get_qualification_results(limit=200):
    """Return qualification results with associated lead information."""
    sql = """
        SELECT
            qr.id,
            qr.lead_id,
            qr.model_name,
            qr.score,
            qr.category,
            qr.reasoning,
            qr.missing_information,
            qr.recommended_next_action,
            qr.human_review_required,
            qr.created_at,
            l.lead_reference,
            l.full_name AS contact_name,
            l.email,
            l.company
        FROM qualification_results qr
        LEFT JOIN leads l ON l.id = qr.lead_id
        ORDER BY qr.created_at DESC
        LIMIT %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            return [dict(row) for row in cur.fetchall()]


def get_latest_qualification(lead_id):
    """Return the most recent qualification result for one lead."""
    sql = """
        SELECT *
        FROM qualification_results
        WHERE lead_id = %s
        ORDER BY created_at DESC
        LIMIT 1
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (lead_id,))
            result = cur.fetchone()

    return dict(result) if result else None


# ============================================================
# SALES OWNERS
# ============================================================

def get_sales_owners(available_only=False):
    """Return sales owners, optionally filtering to available owners."""
    sql = """
        SELECT
            id,
            full_name,
            email,
            specialization,
            is_available,
            active_lead_limit,
            created_at
        FROM sales_owners
    """

    if available_only:
        sql += " WHERE is_available = TRUE"

    sql += " ORDER BY full_name"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]


def assign_lead_owner(lead_id, owner_id):
    """Assign a lead to a sales owner."""
    sql = """
        UPDATE leads
        SET assigned_owner_id = %s,
            updated_at = NOW()
        WHERE id = %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (owner_id, lead_id))
            return cur.rowcount > 0


# ============================================================
# EMAIL DRAFTS
# ============================================================

def save_email_draft(
    lead_id,
    recipient_email,
    subject,
    body,
    draft_status="draft"
):
    """Save an AI-generated email draft for review."""
    sql = """
        INSERT INTO email_drafts (
            lead_id,
            recipient_email,
            subject,
            body,
            draft_status
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    lead_id,
                    recipient_email,
                    subject,
                    body,
                    draft_status
                )
            )
            result = cur.fetchone()

    return result["id"]


def get_email_drafts(lead_id=None, limit=200):
    """Return saved email drafts."""
    sql = """
        SELECT
            ed.id,
            ed.lead_id,
            ed.recipient_email,
            ed.subject,
            ed.body,
            ed.draft_status,
            ed.approved_by,
            ed.approved_at,
            ed.created_at,
            ed.updated_at,
            l.lead_reference,
            l.full_name AS contact_name,
            l.company
        FROM email_drafts ed
        LEFT JOIN leads l ON l.id = ed.lead_id
    """

    params = []

    if lead_id is not None:
        sql += " WHERE ed.lead_id = %s"
        params.append(lead_id)

    sql += " ORDER BY ed.created_at DESC LIMIT %s"
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(row) for row in cur.fetchall()]


def update_email_draft_status(
    draft_id,
    draft_status,
    approved_by=None
):
    """Update an email draft's status and approval information."""
    sql = """
        UPDATE email_drafts
        SET
            draft_status = %s,
            approved_by = CASE
                WHEN %s IS NOT NULL THEN %s
                ELSE approved_by
            END,
            approved_at = CASE
                WHEN %s IS NOT NULL THEN NOW()
                ELSE approved_at
            END,
            updated_at = NOW()
        WHERE id = %s
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    draft_status,
                    approved_by,
                    approved_by,
                    approved_by,
                    draft_id
                )
            )
            return cur.rowcount > 0

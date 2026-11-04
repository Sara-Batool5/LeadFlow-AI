
import os
import uuid
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor, Json


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_url():
    """
    Get the Neon PostgreSQL connection string from Streamlit
    secrets or environment variables.
    """
    try:
        import streamlit as st

        database_url = st.secrets.get("NEON_DATABASE_URL", None)
        if database_url:
            return database_url
    except Exception:
        pass

    database_url = os.getenv("NEON_DATABASE_URL")

    if not database_url:
        raise ValueError(
            "NEON_DATABASE_URL is missing. Add it to Streamlit "
            "Cloud Secrets or your environment variables."
        )

    return database_url


def _connect():
    """Create a PostgreSQL connection."""
    return psycopg2.connect(
        get_database_url(),
        sslmode="require",
        cursor_factory=RealDictCursor,
        connect_timeout=15
    )


def test_connection():
    """Test the Neon database connection."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS version")
                result = cur.fetchone()

        return {
            "success": True,
            "message": "Successfully connected to Neon PostgreSQL.",
            "version": result["version"]
        }

    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_schema():
    """
    Preserve the existing database tables.

    This function only creates useful indexes if they do not
    already exist. It does NOT recreate tables, change ID types,
    or delete existing records.
    """

    index_queries = [
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

    with _connect() as conn:
        with conn.cursor() as cur:
            for query in index_queries:
                cur.execute(query)

    return True


def get_table_counts():
    """Return record counts for the main LeadFlow tables."""

    tables = [
        "leads",
        "sales_owners",
        "qualification_results",
        "email_drafts",
        "workflow_events"
    ]

    counts = {}

    with _connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                # Table names are selected only from the fixed list above.
                cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
                counts[table] = cur.fetchone()["total"]

    return counts


# ============================================================
# NORMALIZATION HELPERS
# ============================================================

def _normalize(value):
    """Normalize text for reliable comparisons."""
    return str(value or "").strip().lower()


def _normalize_website(value):
    """Normalize a website URL for duplicate comparisons."""
    website = _normalize(value)

    if not website:
        return ""

    website = website.replace("https://", "")
    website = website.replace("http://", "")
    website = website.replace("www.", "")

    return website.split("/")[0].strip().rstrip(".")


# ============================================================
# LEAD DUPLICATE DETECTION
# ============================================================

def find_potential_duplicates(lead):
    """
    Find likely duplicate leads without flagging unrelated
    contacts merely because they work for the same company.

    Matching rules:
    1. Exact email address.
    2. Exact contact name AND exact company.
    3. Exact contact name AND exact website.

    Same company alone, same email domain alone, or similar
    name fragments are not considered sufficient matches.
    """

    email = _normalize(lead.get("email"))
    name = _normalize(
        lead.get("contact_name") or lead.get("full_name")
    )
    company = _normalize(lead.get("company"))
    website = _normalize_website(lead.get("website"))

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    lead_reference,
                    full_name AS contact_name,
                    email,
                    company,
                    website,
                    status,
                    created_at
                FROM leads
                ORDER BY created_at DESC
                LIMIT 500
            """)

            rows = cur.fetchall()

    matches = []

    for row in rows:
        existing_email = _normalize(row.get("email"))
        existing_name = _normalize(row.get("contact_name"))
        existing_company = _normalize(row.get("company"))
        existing_website = _normalize_website(
            row.get("website")
        )

        match_type = None

        if email and email == existing_email:
            match_type = "exact_email"

        elif (
            name
            and company
            and name == existing_name
            and company == existing_company
        ):
            match_type = "same_contact_and_company"

        elif (
            name
            and website
            and name == existing_name
            and website == existing_website
        ):
            match_type = "same_contact_and_website"

        if match_type:
            item = dict(row)
            item["match_type"] = match_type
            item["created_at"] = str(
                item.get("created_at") or ""
            )

            # Do not expose the internal database ID in the UI.
            item.pop("id", None)

            matches.append(item)

    return matches[:10]


# ============================================================
# LEAD CREATION
# ============================================================

def create_lead(lead):
    """
    Insert a new lead into the existing leads table.

    App-facing names are mapped to the actual Neon column names:
    contact_name -> full_name
    description  -> need_description
    budget       -> budget_range
    """

    lead_reference = (
        lead.get("lead_reference")
        or f"LD-{uuid.uuid4().hex[:8].upper()}"
    )

    contact_name = (
        lead.get("contact_name")
        or lead.get("full_name")
        or ""
    )

    description = (
        lead.get("description")
        or lead.get("need_description")
        or ""
    )

    budget = (
        lead.get("budget")
        or lead.get("budget_range")
        or ""
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
                    consent_to_contact
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                RETURNING
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
            """, (
                lead_reference,
                contact_name,
                lead.get("email", ""),
                lead.get("company", ""),
                lead.get("job_title", ""),
                lead.get("website", ""),
                lead.get("company_size", ""),
                lead.get("industry", ""),
                lead.get("country", ""),
                lead.get("source", ""),
                description,
                budget,
                lead.get("timeline", ""),
                lead.get("status", "New"),
                lead.get("priority", "Unqualified"),
                lead.get("consent_to_contact", False)
            ))

            new_lead = dict(cur.fetchone())

    return new_lead


# ============================================================
# LEAD RETRIEVAL
# ============================================================

def get_leads(limit=500):
    """Retrieve leads using app-friendly column names."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]


def get_lead_by_id(lead_id):
    """Retrieve one lead by its existing BIGINT ID."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (lead_id,))

            row = cur.fetchone()

    return dict(row) if row else None


# ============================================================
# LEAD UPDATES
# ============================================================

def update_lead_status(lead_id, status):
    """Update the status of an existing lead."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE leads
                SET
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (status, lead_id))

            return cur.rowcount > 0


def update_lead_qualification(lead_id, priority=None):
    """
    Update the lead priority after AI qualification.

    The qualification details themselves are stored separately
    in qualification_results.
    """

    if not priority:
        return False

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE leads
                SET
                    priority = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (priority, lead_id))

            return cur.rowcount > 0


# ============================================================
# WORKFLOW EVENTS
# ============================================================

def create_workflow_event(
    lead_id,
    event_type,
    event_status="completed",
    message="",
    details=None,
    actor="system"
):
    """Save a workflow event for a lead."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (
                lead_id,
                event_type,
                event_status,
                message,
                Json(details or {}),
                actor
            ))

            result = cur.fetchone()

    return result["id"]


def get_workflow_events(limit=200):
    """Retrieve workflow history with lead information."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    we.id,
                    we.lead_id,
                    l.lead_reference,
                    l.full_name AS contact_name,
                    l.company,
                    we.event_type,
                    we.event_status,
                    we.message,
                    we.details,
                    we.actor,
                    we.created_at
                FROM workflow_events we
                LEFT JOIN leads l
                    ON l.id = we.lead_id
                ORDER BY we.created_at DESC
                LIMIT %s
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]


# ============================================================
# AI QUALIFICATION RESULTS
# ============================================================

def save_qualification_result(
    lead_id,
    model_name,
    score,
    category,
    reasoning,
    missing_information=None,
    recommended_next_action="",
    human_review_required=False
):
    """Save an AI qualification result."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (
                lead_id,
                model_name,
                score,
                category,
                reasoning,
                Json(missing_information or []),
                recommended_next_action,
                human_review_required
            ))

            result = cur.fetchone()

    return result["id"]


def get_qualification_results(limit=200):
    """Retrieve AI qualification history with lead details."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    qr.id,
                    qr.lead_id,
                    l.lead_reference,
                    l.full_name AS contact_name,
                    l.email,
                    l.company,
                    qr.model_name,
                    qr.score,
                    qr.category,
                    qr.reasoning,
                    qr.missing_information,
                    qr.recommended_next_action,
                    qr.human_review_required,
                    qr.created_at
                FROM qualification_results qr
                LEFT JOIN leads l
                    ON l.id = qr.lead_id
                ORDER BY qr.created_at DESC
                LIMIT %s
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]


def get_qualification_by_lead_id(lead_id):
    """Retrieve the latest qualification result for one lead."""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    id,
                    lead_id,
                    model_name,
                    score,
                    category,
                    reasoning,
                    missing_information,
                    recommended_next_action,
                    human_review_required,
                    created_at
                FROM qualification_results
                WHERE lead_id = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (lead_id,))

            row = cur.fetchone()

    return dict(row) if row else None

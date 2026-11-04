import json
import os
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


class DatabaseConfigurationError(RuntimeError):
    pass


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_url():
    try:
        import streamlit as st
        value = st.secrets.get("NEON_DATABASE_URL")
    except Exception:
        value = None

    return value or os.getenv("NEON_DATABASE_URL")


def _connect():
    url = get_database_url()

    if not url:
        raise DatabaseConfigurationError(
            "NEON_DATABASE_URL is not configured."
        )

    return psycopg.connect(
        url,
        row_factory=dict_row,
        connect_timeout=15
    )


def test_connection():
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

        return True

    except Exception:
        return False


# ============================================================
# SCHEMA INITIALIZATION
# IMPORTANT:
# Existing Neon tables are preserved.
# IDs and foreign-key relationships are not changed.
# ============================================================

def initialize_schema():
    """
    The Neon database already contains the required tables.

    This function intentionally does not recreate tables,
    change ID types, or run destructive migrations.
    It only ensures compatible indexes exist.
    """

    sqls = [
        """
        CREATE INDEX IF NOT EXISTS idx_leads_email_lower
        ON leads (LOWER(email))
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leads_created_at
        ON leads (created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_events_created_at
        ON workflow_events (created_at DESC)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_qualification_lead_created
        ON qualification_results (lead_id, created_at DESC)
        """
    ]

    with _connect() as conn:
        with conn.cursor() as cur:
            for sql in sqls:
                cur.execute(sql)


# ============================================================
# TABLE COUNTS
# ============================================================

def get_table_counts():
    result = {}

    tables = [
        "leads",
        "sales_owners",
        "qualification_results",
        "email_drafts",
        "workflow_events"
    ]

    with _connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(
                    f"SELECT COUNT(*) AS count FROM {table}"
                )

                result[table] = int(cur.fetchone()["count"])

    return result


# ============================================================
# DUPLICATE DETECTION HELPERS
# ============================================================

def _website(value):
    value = (value or "").strip().lower()

    value = value.replace("https://", "")
    value = value.replace("http://", "")

    value = value.split("/")[0]

    return value.removeprefix("www.")


def _domain(value):
    if value and "@" in value:
        return value.strip().lower().split("@")[-1]

    return ""


def _free(domain):
    free_domains = {
        "gmail.com",
        "yahoo.com",
        "hotmail.com",
        "outlook.com",
        "live.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "mail.com",
        "yandex.com",
        "gmx.com"
    }

    return domain in free_domains


# ============================================================
# FIND POTENTIAL DUPLICATES
# ============================================================

def find_potential_duplicates(lead):

    email = (lead.get("email") or "").strip().lower()

    company = (lead.get("company") or "").strip().lower()

    name = (
        lead.get("contact_name")
        or lead.get("full_name")
        or ""
    ).strip().lower()

    website = _website(lead.get("website"))

    domain = _domain(email)

    with _connect() as conn:
        with conn.cursor() as cur:

            cur.execute(
                """
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
                """
            )

            rows = cur.fetchall()

    found = []

    for row in rows:

        existing_email = (
            row.get("email") or ""
        ).strip().lower()

        existing_company = (
            row.get("company") or ""
        ).strip().lower()

        existing_name = (
            row.get("contact_name") or ""
        ).strip().lower()

        existing_website = _website(
            row.get("website")
        )

        existing_domain = _domain(existing_email)

        match_types = []

        # Exact email match
        if email and email == existing_email:

            match_types.append("exact_email")

        else:

            # Similar contact name
            if (
                name
                and existing_name
                and (
                    name == existing_name
                    or name in existing_name
                    or existing_name in name
                )
            ):
                match_types.append("similar_contact_name")

            # Similar company
            if (
                company
                and existing_company
                and (
                    company == existing_company
                    or company in existing_company
                    or existing_company in company
                )
            ):
                match_types.append("same_or_similar_company")

            # Similar website
            if (
                website
                and existing_website
                and (
                    website == existing_website
                    or website.endswith("." + existing_website)
                    or existing_website.endswith("." + website)
                )
            ):
                match_types.append("same_website_domain")

            # Same business email domain
            if (
                domain
                and domain == existing_domain
                and not _free(domain)
            ):
                match_types.append("same_business_email_domain")

        if match_types:

            item = dict(row)

            item["match_type"] = ", ".join(match_types)

            item["created_at"] = str(
                item.get("created_at", "")
            )

            # Do not expose database ID in duplicate preview
            item.pop("id", None)

            found.append(item)

    return found[:10]


# ============================================================
# CREATE NEW LEAD
# Uses actual Neon column names and BIGINT auto-generated IDs.
# ============================================================

def create_lead(lead):

    reference = (
        "LF-"
        + datetime.now(timezone.utc).strftime("%y%m%d")
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )

    contact_name = (
        lead.get("contact_name")
        or lead.get("full_name")
        or ""
    ).strip()

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                INSERT INTO leads (
                    lead_reference,
                    full_name,
                    email,
                    company,
                    website,
                    job_title,
                    industry,
                    country,
                    company_size,
                    budget_range,
                    timeline,
                    need_description
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    reference,
                    contact_name,
                    (lead.get("email") or "").strip(),
                    lead.get("company") or "",
                    lead.get("website") or None,
                    lead.get("job_title") or None,
                    lead.get("industry") or None,
                    lead.get("country") or None,
                    lead.get("company_size") or None,
                    lead.get("budget") or lead.get("budget_range") or None,
                    lead.get("timeline") or None,
                    lead.get("description") or lead.get("need_description") or None
                )
            )

            inserted_lead = cur.fetchone()

            lead_id = inserted_lead["id"]

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    actor,
                    details
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    lead_id,
                    "lead_created",
                    "completed",
                    f"Lead {reference} was created and saved.",
                    "lead_intake",
                    json.dumps({
                        "lead_reference": reference
                    })
                )
            )

    return reference


# ============================================================
# GET ALL LEADS
# Maps actual database columns to app-facing names.
# ============================================================

def get_leads():

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
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
                    company_size,
                    budget_range AS budget,
                    timeline,
                    need_description AS description,
                    status,
                    priority,
                    created_at,
                    updated_at
                FROM leads
                ORDER BY created_at DESC
                """
            )

            rows = cur.fetchall()

    for row in rows:

        row["id"] = str(row["id"])

        row["created_at"] = str(
            row["created_at"]
        )

        row["updated_at"] = str(
            row["updated_at"]
        )

    return rows


# ============================================================
# WORKFLOW HISTORY
# ============================================================

def get_workflow_events(limit=250):

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    e.event_type,
                    e.message,
                    e.actor,
                    e.details,
                    e.created_at,
                    l.lead_reference,
                    l.full_name AS contact_name,
                    l.company
                FROM workflow_events e
                LEFT JOIN leads l
                    ON l.id = e.lead_id
                ORDER BY e.created_at DESC
                LIMIT %s
                """,
                (limit,)
            )

            rows = cur.fetchall()

    for row in rows:

        row["details"] = json.dumps(
            row.get("details") or {},
            default=str
        )

        row["created_at"] = str(
            row["created_at"]
        )

    return rows


# ============================================================
# SAVE AI QUALIFICATION RESULT
# Uses existing BIGINT lead_id.
# ============================================================

def save_qualification_result(lead_id, result):

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
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
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s
                )
                """,
                (
                    lead_id,
                    result["model_name"],
                    result["score"],
                    result["category"],
                    result["reasoning"],
                    json.dumps(
                        result["missing_information"]
                    ),
                    result["recommended_next_action"],
                    result["human_review_required"]
                )
            )

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    actor,
                    details
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s::jsonb
                )
                """,
                (
                    lead_id,
                    "lead_ai_qualified",
                    "completed",
                    (
                        f"AI qualification saved: "
                        f"{result['score']}/100, "
                        f"category {result['category']}."
                    ),
                    "groq_ai_qualification",
                    json.dumps({
                        key: result[key]
                        for key in [
                            "model_name",
                            "score",
                            "category",
                            "priority"
                        ]
                        if key in result
                    })
                )
            )


# ============================================================
# UPDATE LEAD QUALIFICATION
# ============================================================

def update_lead_qualification(
    lead_id,
    category,
    priority
):

    status = (
        "needs_review"
        if category == "needs_review"
        else "qualified"
    )

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                UPDATE leads
                SET
                    status = %s,
                    priority = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    status,
                    priority,
                    lead_id
                )
            )


# ============================================================
# GET QUALIFICATION HISTORY FOR A LEAD
# ============================================================

def get_qualification_results(lead_id, limit=10):

    with _connect() as conn:

        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
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
                LIMIT %s
                """,
                (
                    lead_id,
                    limit
                )
            )

            rows = cur.fetchall()

    for row in rows:

        row["missing_information"] = json.dumps(
            row.get("missing_information") or [],
            ensure_ascii=False
        )

        row["created_at"] = str(
            row["created_at"]
        )

    return rows

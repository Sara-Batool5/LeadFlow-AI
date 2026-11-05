
import os
import re
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor, Json


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_database_url():
    try:
        import streamlit as st
        value = st.secrets.get("NEON_DATABASE_URL")
        if value:
            return value
    except Exception:
        pass

    return os.getenv("NEON_DATABASE_URL")


def _connect():
    database_url = get_database_url()

    if not database_url:
        raise ValueError(
            "NEON_DATABASE_URL is missing. Add it to Streamlit Cloud secrets."
        )

    return psycopg2.connect(
        database_url,
        sslmode="require",
        cursor_factory=RealDictCursor,
        connect_timeout=20,
    )


def test_connection():
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS version;")
                row = cur.fetchone()
        return True, row["version"]
    except Exception as exc:
        return False, str(exc)


def initialize_schema():
    """
    Do not recreate or alter existing tables.
    Only create safe indexes on the user's existing schema.
    """
    statements = [
        """
        CREATE INDEX IF NOT EXISTS idx_leads_created_at
        ON leads (created_at DESC);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leads_status
        ON leads (status);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_leads_assigned_owner
        ON leads (assigned_owner_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_workflow_events_lead
        ON workflow_events (lead_id, created_at DESC);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_email_drafts_lead
        ON email_drafts (lead_id, created_at DESC);
        """,
    ]

    with _connect() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)


def get_table_counts():
    tables = [
        "leads",
        "workflow_events",
        "qualification_results",
        "sales_owners",
        "email_drafts",
    ]

    counts = {}

    with _connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT COUNT(*) AS total FROM {table};")
                counts[table] = cur.fetchone()["total"]

    return counts


# ============================================================
# GENERAL HELPERS
# ============================================================

def _clean(value):
    if value is None:
        return ""
    return str(value).strip()


def _normal_text(value):
    return re.sub(r"\s+", " ", _clean(value).lower())


def _normal_website(value):
    website = _clean(value).lower()
    website = re.sub(r"^https?://", "", website)
    website = re.sub(r"^www\.", "", website)
    return website.split("/")[0].strip()


def _lead_value(lead, *keys):
    for key in keys:
        value = lead.get(key)
        if value is not None and _clean(value):
            return value
    return None


def _lead_reference(lead):
    return (
        lead.get("lead_reference")
        or f"LF-{datetime.now(timezone.utc).strftime('%y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    )


def _normalize_lead_priority(value):
    """Return a value accepted by the leads.priority database constraint."""
    priority_value = _clean(value).lower()

    category_to_priority = {
        "high_fit": "high",
        "medium_fit": "medium",
        "low_fit": "low",
        "needs_review": "unassessed",
    }

    if priority_value in {"unassessed", "low", "medium", "high", "urgent"}:
        return priority_value

    return category_to_priority.get(priority_value, "unassessed")


# ============================================================
# LEADS
# ============================================================

def find_potential_duplicates(lead):
    email = _normal_text(_lead_value(lead, "email"))
    name = _normal_text(_lead_value(lead, "contact_name", "full_name"))
    company = _normal_text(_lead_value(lead, "company"))
    website = _normal_website(_lead_value(lead, "website"))

    if not any([email, name]):
        return []

    query = """
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
        WHERE
            (%s <> '' AND LOWER(TRIM(COALESCE(email, ''))) = %s)
            OR
            (
                %s <> ''
                AND %s <> ''
                AND LOWER(TRIM(COALESCE(full_name, ''))) = %s
                AND LOWER(TRIM(COALESCE(company, ''))) = %s
            )
            OR
            (
                %s <> ''
                AND %s <> ''
                AND LOWER(TRIM(COALESCE(full_name, ''))) = %s
                AND LOWER(
                    REGEXP_REPLACE(
                        REGEXP_REPLACE(COALESCE(website, ''), '^https?://', ''),
                        '^www\\.',
                        ''
                    )
                ) LIKE %s
            )
        ORDER BY created_at DESC
        LIMIT 10;
    """

    website_pattern = website if website else ""

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    email, email,
                    name, company, name, company,
                    name, website, name, website_pattern,
                ),
            )
            return [dict(row) for row in cur.fetchall()]


def create_lead(lead):
    full_name = _clean(_lead_value(lead, "contact_name", "full_name"))
    description = _clean(
        _lead_value(lead, "description", "need_description")
    ) or "Not provided"

    values = (
        _lead_reference(lead),
        full_name,
        _clean(lead.get("email")),
        _clean(lead.get("company")),
        _clean(lead.get("job_title")),
        _clean(lead.get("website")),
        _clean(lead.get("company_size")),
        _clean(lead.get("industry")),
        _clean(lead.get("country")),
        _clean(lead.get("source")) or "website_form",
        description,
        _clean(_lead_value(lead, "budget", "budget_range")),
        _clean(lead.get("timeline")),
        _clean(lead.get("status")) or "new",
        _normalize_lead_priority(lead.get("priority")),
        bool(lead.get("consent_to_contact", False)),
    )

    query = """
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
            consent_to_contact,
            created_at,
            updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, COALESCE(%s, 'Not provided'),
            %s, %s, %s, %s, %s, NOW(), NOW()
        )
        RETURNING id, lead_reference;
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
            return dict(cur.fetchone())


def get_leads(search=""):
    query = """
        SELECT
            l.id,
            l.lead_reference,
            l.full_name AS contact_name,
            l.email,
            l.company,
            l.job_title,
            l.website,
            l.company_size,
            l.industry,
            l.country,
            l.source,
            l.need_description AS description,
            l.budget_range AS budget,
            l.timeline,
            l.status,
            l.priority,
            l.assigned_owner_id,
            l.duplicate_of_lead_id,
            l.consent_to_contact,
            l.created_at,
            l.updated_at,
            s.full_name AS assigned_owner,
            s.email AS assigned_owner_email
        FROM leads l
        LEFT JOIN sales_owners s ON s.id = l.assigned_owner_id
    """

    params = []

    if search:
        query += """
            WHERE
                l.full_name ILIKE %s
                OR l.email ILIKE %s
                OR l.company ILIKE %s
                OR l.lead_reference ILIKE %s
        """
        term = f"%{search}%"
        params = [term, term, term, term]

    query += " ORDER BY l.created_at DESC;"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def get_lead_by_id(lead_id):
    query = """
        SELECT
            l.*,
            l.full_name AS contact_name,
            l.need_description AS description,
            l.budget_range AS budget,
            s.full_name AS assigned_owner,
            s.email AS assigned_owner_email
        FROM leads l
        LEFT JOIN sales_owners s ON s.id = l.assigned_owner_id
        WHERE l.id = %s;
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (lead_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def update_lead_status(lead_id, status):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE leads
                SET status = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (status, lead_id),
            )


def update_lead_qualification(lead_id, score, category):
    """Update the lead priority using a valid leads.priority value.

    The detailed qualification category (high_fit, medium_fit, low_fit,
    needs_review) is stored separately in qualification_results.category.
    The leads.priority column accepts only unassessed, low, medium, high,
    or urgent.
    """

    priority = _normalize_lead_priority(category)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE leads
                SET priority = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (priority, lead_id),
            )


# ============================================================
# QUALIFICATION RESULTS
# ============================================================

def save_qualification_result(lead_id, result, model_name="Groq"):
    query = """
        INSERT INTO qualification_results (
            lead_id,
            model_name,
            score,
            category,
            reasoning,
            missing_information,
            recommended_next_action,
            human_review_required,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        RETURNING id;
    """

    missing = result.get("missing_information", [])
    if not isinstance(missing, list):
        missing = [str(missing)]

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    lead_id,
                    model_name,
                    int(result.get("score", 0)),
                    _clean(result.get("category")) or "Needs Review",
                    _clean(result.get("reasoning")),
                    Json(missing),
                    _clean(result.get("recommended_next_action")),
                    bool(result.get("human_review_required", True)),
                ),
            )
            return dict(cur.fetchone())


def get_qualification_results(lead_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM qualification_results
                WHERE lead_id = %s
                ORDER BY created_at DESC;
                """,
                (lead_id,),
            )
            return [dict(row) for row in cur.fetchall()]


# ============================================================
# WORKFLOW HISTORY / AUDIT EVENTS
# ============================================================

def create_workflow_event(
    lead_id,
    event_type,
    message,
    event_status="completed",
    details=None,
    actor="LeadFlow AI",
):
    query = """
        INSERT INTO workflow_events (
            lead_id,
            event_type,
            event_status,
            message,
            details,
            actor,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        RETURNING id;
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                query,
                (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    Json(details or {}),
                    actor,
                ),
            )
            return dict(cur.fetchone())


def get_workflow_events(lead_id=None):
    query = """
        SELECT
            w.id,
            w.lead_id,
            w.event_type,
            w.event_status,
            w.message,
            w.details,
            w.actor,
            w.created_at,
            l.lead_reference,
            l.full_name AS contact_name,
            l.company
        FROM workflow_events w
        LEFT JOIN leads l ON l.id = w.lead_id
    """

    params = []

    if lead_id is not None:
        query += " WHERE w.lead_id = %s"
        params.append(lead_id)

    query += " ORDER BY w.created_at DESC LIMIT 500;"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


# ============================================================
# SALES OWNERS AND WORKLOAD
# ============================================================

def get_sales_owners():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM sales_owners
                ORDER BY full_name;
                """
            )
            return [dict(row) for row in cur.fetchall()]


def create_sales_owner(full_name, email, specialization, active_lead_limit):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sales_owners (
                    full_name,
                    email,
                    specialization,
                    is_available,
                    active_lead_limit,
                    created_at
                )
                VALUES (%s, %s, %s, TRUE, %s, NOW())
                RETURNING id;
                """,
                (
                    _clean(full_name),
                    _clean(email),
                    _clean(specialization),
                    int(active_lead_limit),
                ),
            )
            return dict(cur.fetchone())


def update_sales_owner_availability(owner_id, is_available):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE sales_owners
                SET is_available = %s
                WHERE id = %s;
                """,
                (bool(is_available), owner_id),
            )


def get_owner_workloads():
    query = """
        SELECT
            s.id,
            s.full_name,
            s.email,
            s.specialization,
            s.is_available,
            s.active_lead_limit,
            COUNT(
                CASE
                    WHEN LOWER(COALESCE(l.status, '')) NOT IN
                    ('closed', 'won', 'lost', 'disqualified')
                    THEN 1
                END
            ) AS active_leads
        FROM sales_owners s
        LEFT JOIN leads l ON l.assigned_owner_id = s.id
        GROUP BY s.id
        ORDER BY s.full_name;
    """

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]


def _specialization_match(specialization, lead):
    """Return True only when a specialization exactly matches the lead industry."""
    industry = _normal_text(lead.get("industry"))
    specialization = _normal_text(specialization)

    if not industry or not specialization:
        return False

    terms = [
        item.strip()
        for item in re.split(r"[,;/|]+", specialization)
        if item.strip()
    ]

    return industry in terms


def _is_general_business_specialization(specialization):
    """Identify owners who can serve as the general fallback."""
    normalized = _normal_text(specialization)
    general_labels = {
        "general business",
        "general",
        "all industries",
        "all",
        "any",
        "*",
    }
    return normalized in general_labels


def assign_lead_automatically(lead_id):
    lead = get_lead_by_id(lead_id)

    if not lead:
        return False, "Lead not found.", None

    industry = _clean(lead.get("industry")) or "unspecified industry"

    with _connect() as conn:
        with conn.cursor() as cur:
            # Read available owners and calculate workload. Avoid row-locking
            # clauses so this query remains compatible with the hosted database.
            cur.execute(
                """
                SELECT
                    s.id,
                    s.full_name,
                    s.specialization,
                    s.is_available,
                    s.active_lead_limit,
                    COUNT(
                        CASE
                            WHEN LOWER(COALESCE(l.status, '')) NOT IN
                            ('closed', 'won', 'lost', 'disqualified')
                            THEN 1
                        END
                    ) AS active_leads
                FROM sales_owners s
                LEFT JOIN leads l ON l.assigned_owner_id = s.id
                WHERE s.is_available = TRUE
                GROUP BY s.id
                ORDER BY s.id;
                """
            )
            owners = [dict(row) for row in cur.fetchall()]

            eligible = [
                owner for owner in owners
                if int(owner["active_leads"]) < int(owner["active_lead_limit"])
            ]

            if not eligible:
                return False, "No available sales owner has remaining capacity.", None

            # First preference: an exact match with the lead's industry.
            matching = [
                owner for owner in eligible
                if _specialization_match(owner.get("specialization"), lead)
            ]

            if matching:
                candidates = matching
                assignment_reason = "exact_industry_match"
            else:
                # Second preference: a General Business owner only.
                general_business_owners = [
                    owner for owner in eligible
                    if _is_general_business_specialization(
                        owner.get("specialization")
                    )
                ]

                if not general_business_owners:
                    return (
                        False,
                        f"No available owner has an exact match for '{industry}' "
                        "or a General Business specialization. Lead remains "
                        "unassigned for manual assignment.",
                        None,
                    )

                candidates = general_business_owners
                assignment_reason = "general_business_fallback"

            # Balance workload among owners within the selected preference group.
            candidates.sort(
                key=lambda owner: (
                    int(owner["active_leads"]) / max(
                        int(owner["active_lead_limit"]), 1
                    ),
                    int(owner["active_leads"]),
                )
            )

            selected = candidates[0]

            cur.execute(
                """
                UPDATE leads
                SET assigned_owner_id = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (selected["id"], lead_id),
            )

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id, event_type, event_status,
                    message, details, actor, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    lead_id,
                    "automatic_owner_assignment",
                    "completed",
                    f"Lead assigned automatically to {selected['full_name']}.",
                    Json({
                        "owner_id": selected["id"],
                        "owner_name": selected["full_name"],
                        "specialization": selected["specialization"],
                        "lead_industry": industry,
                        "assignment_reason": assignment_reason,
                    }),
                    "LeadFlow AI",
                ),
            )

    if assignment_reason == "exact_industry_match":
        message = (
            f"Assigned to {selected['full_name']} using an exact industry match."
        )
    else:
        message = (
            f"Assigned to {selected['full_name']} using the General Business fallback."
        )

    return True, message, selected


def assign_lead_owner(lead_id, owner_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    s.id,
                    s.full_name,
                    s.is_available,
                    s.active_lead_limit,
                    COUNT(
                        CASE
                            WHEN LOWER(COALESCE(l.status, '')) NOT IN
                            ('closed', 'won', 'lost', 'disqualified')
                            THEN 1
                        END
                    ) AS active_leads
                FROM sales_owners s
                LEFT JOIN leads l ON l.assigned_owner_id = s.id
                WHERE s.id = %s
                GROUP BY s.id;
                """,
                (owner_id,),
            )
            owner = cur.fetchone()

            if not owner:
                return False, "Sales owner not found."

            if not owner["is_available"]:
                return False, "This sales owner is currently unavailable."

            if int(owner["active_leads"]) >= int(owner["active_lead_limit"]):
                return False, "This sales owner has reached their lead capacity."

            cur.execute(
                """
                UPDATE leads
                SET assigned_owner_id = %s, updated_at = NOW()
                WHERE id = %s;
                """,
                (owner_id, lead_id),
            )

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id, event_type, event_status,
                    message, details, actor, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    lead_id,
                    "manual_owner_assignment",
                    "completed",
                    f"Lead manually assigned to {owner['full_name']}.",
                    Json({
                        "owner_id": owner_id,
                        "owner_name": owner["full_name"],
                    }),
                    "Administrator",
                ),
            )

    return True, f"Lead assigned to {owner['full_name']}."


def unassign_lead_owner(lead_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.full_name
                FROM leads l
                LEFT JOIN sales_owners s ON s.id = l.assigned_owner_id
                WHERE l.id = %s;
                """,
                (lead_id,),
            )
            row = cur.fetchone()

            cur.execute(
                """
                UPDATE leads
                SET assigned_owner_id = NULL, updated_at = NOW()
                WHERE id = %s;
                """,
                (lead_id,),
            )

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id, event_type, event_status,
                    message, details, actor, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    lead_id,
                    "owner_unassigned",
                    "completed",
                    "Sales owner assignment was removed.",
                    Json({"previous_owner": row["full_name"] if row else None}),
                    "Administrator",
                ),
            )


# ============================================================
# EMAIL DRAFTS — STEP 7
# ============================================================

def save_email_draft(
    lead_id,
    recipient_email,
    subject,
    body,
    draft_id=None,
):
    """
    Create a new draft, or update an existing draft.
    Saving content resets the status to pending_review.
    """

    recipient_email = _clean(recipient_email)
    subject = _clean(subject)
    body = _clean(body)

    if not recipient_email:
        raise ValueError("Recipient email is required.")

    if not subject:
        raise ValueError("Email subject is required.")

    if not body:
        raise ValueError("Email body is required.")

    with _connect() as conn:
        with conn.cursor() as cur:
            if draft_id:
                cur.execute(
                    """
                    UPDATE email_drafts
                    SET
                        recipient_email = %s,
                        subject = %s,
                        body = %s,
                        draft_status = 'pending_review',
                        approved_by = NULL,
                        approved_at = NULL,
                        updated_at = NOW()
                    WHERE id = %s AND lead_id = %s
                    RETURNING id;
                    """,
                    (recipient_email, subject, body, draft_id, lead_id),
                )
                result = cur.fetchone()

                if not result:
                    raise ValueError("The selected email draft could not be found.")

                saved_id = result["id"]
                event_type = "email_draft_updated"
                message = "Follow-up email draft was updated."

            else:
                cur.execute(
                    """
                    INSERT INTO email_drafts (
                        lead_id,
                        recipient_email,
                        subject,
                        body,
                        draft_status,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, 'pending_review', NOW(), NOW())
                    RETURNING id;
                    """,
                    (lead_id, recipient_email, subject, body),
                )
                saved_id = cur.fetchone()["id"]
                event_type = "email_draft_created"
                message = "A new follow-up email draft was saved."

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    details,
                    actor,
                    created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    lead_id,
                    event_type,
                    "completed",
                    message,
                    Json({
                        "email_draft_id": saved_id,
                        "recipient_email": recipient_email,
                        "subject": subject,
                    }),
                    "LeadFlow AI",
                ),
            )

    return saved_id


def get_email_drafts(lead_id=None):
    query = """
        SELECT
            e.id,
            e.lead_id,
            e.recipient_email,
            e.subject,
            e.body,
            e.draft_status,
            e.approved_by,
            e.approved_at,
            e.created_at,
            e.updated_at,
            l.lead_reference,
            l.full_name AS contact_name,
            l.company
        FROM email_drafts e
        LEFT JOIN leads l ON l.id = e.lead_id
    """

    params = []

    if lead_id is not None:
        query += " WHERE e.lead_id = %s"
        params.append(lead_id)

    query += " ORDER BY e.updated_at DESC;"

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def approve_email_draft(draft_id, approved_by="Administrator"):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE email_drafts
                SET
                    draft_status = 'approved',
                    approved_by = %s,
                    approved_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING lead_id, recipient_email, subject;
                """,
                (approved_by, draft_id),
            )
            draft = cur.fetchone()

            if not draft:
                return False, "Email draft not found."

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id, event_type, event_status,
                    message, details, actor, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    draft["lead_id"],
                    "email_draft_approved",
                    "completed",
                    "Follow-up email draft was approved. No email was sent.",
                    Json({
                        "email_draft_id": draft_id,
                        "recipient_email": draft["recipient_email"],
                        "subject": draft["subject"],
                    }),
                    approved_by,
                ),
            )

    return True, "Draft approved. No email was sent."


def delete_email_draft(draft_id):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM email_drafts
                WHERE id = %s
                RETURNING lead_id;
                """,
                (draft_id,),
            )
            row = cur.fetchone()

            if not row:
                return False

            cur.execute(
                """
                INSERT INTO workflow_events (
                    lead_id, event_type, event_status,
                    message, details, actor, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW());
                """,
                (
                    row["lead_id"],
                    "email_draft_deleted",
                    "completed",
                    "A saved email draft was deleted.",
                    Json({"email_draft_id": draft_id}),
                    "Administrator",
                ),
            )

    return True

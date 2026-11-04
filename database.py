
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
        value = st.secrets.get("NEON_DATABASE_URL")
        if value:
            return value
    except Exception:
        pass

    value = os.getenv("NEON_DATABASE_URL")
    if not value:
        raise ValueError(
            "NEON_DATABASE_URL is missing. Add it to Streamlit Cloud secrets."
        )

    return value


def _connect():
    return psycopg2.connect(
        get_database_url(),
        sslmode="require",
        connect_timeout=15,
        cursor_factory=RealDictCursor
    )


def test_connection():
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version() AS version")
                result = cur.fetchone()

        return True, result["version"]

    except Exception as exc:
        return False, str(exc)


# ============================================================
# DATABASE INITIALIZATION
# Does not create, drop, or alter existing tables.
# ============================================================

def initialize_schema():
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_leads_email_lower ON leads (LOWER(email))",
        "CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads (created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_leads_status ON leads (status)",
        "CREATE INDEX IF NOT EXISTS idx_leads_assigned_owner ON leads (assigned_owner_id)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_events_lead_id ON workflow_events (lead_id)",
        "CREATE INDEX IF NOT EXISTS idx_qualification_results_lead_id ON qualification_results (lead_id)",
        "CREATE INDEX IF NOT EXISTS idx_sales_owners_available ON sales_owners (is_available)"
    ]

    with _connect() as conn:
        with conn.cursor() as cur:
            for statement in indexes:
                cur.execute(statement)

    return True


def get_table_counts():
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
                cur.execute(f"SELECT COUNT(*) AS total FROM {table}")
                counts[table] = int(cur.fetchone()["total"])

    return counts


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _clean(value):
    if value is None:
        return None

    value = str(value).strip()
    return value if value else None


def _normal_text(value):
    value = _clean(value)

    if not value:
        return None

    return re.sub(r"\s+", " ", value).lower()


def _normal_website(value):
    value = _clean(value)

    if not value:
        return None

    value = value.lower().strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"^www\.", "", value)

    return value.rstrip("/")


def _lead_value(lead, *keys):
    for key in keys:
        value = lead.get(key)

        if value is not None and str(value).strip():
            return value

    return None


def _lead_reference():
    return (
        "LF-"
        + datetime.now().strftime("%y%m%d")
        + "-"
        + uuid.uuid4().hex[:6].upper()
    )


# ============================================================
# DUPLICATE DETECTION
# ============================================================

def find_potential_duplicates(lead):
    email = _normal_text(_lead_value(lead, "email"))
    name = _normal_text(
        _lead_value(lead, "contact_name", "full_name")
    )
    company = _normal_text(lead.get("company"))
    website = _normal_website(lead.get("website"))

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
                    priority,
                    created_at
                FROM leads
                ORDER BY created_at DESC
                LIMIT 1000
            """)

            rows = cur.fetchall()

    matches = []

    for row in rows:
        row_email = _normal_text(row.get("email"))
        row_name = _normal_text(row.get("contact_name"))
        row_company = _normal_text(row.get("company"))
        row_website = _normal_website(row.get("website"))

        match_type = None

        if email and row_email and email == row_email:
            match_type = "exact_email"

        elif (
            name
            and row_name
            and company
            and row_company
            and name == row_name
            and company == row_company
        ):
            match_type = "same_contact_company"

        elif (
            name
            and row_name
            and website
            and row_website
            and name == row_name
            and website == row_website
        ):
            match_type = "same_contact_website"

        if match_type:
            item = dict(row)
            item["match_type"] = match_type
            item["created_at"] = str(item.get("created_at", ""))
            matches.append(item)

    return matches[:10]


# ============================================================
# LEAD CREATION
# ============================================================

def create_lead(lead):
    full_name = _clean(
        _lead_value(lead, "contact_name", "full_name")
    )

    email = _normal_text(lead.get("email"))

    if not full_name:
        raise ValueError("Contact name is required.")

    if not email:
        raise ValueError("Email is required.")

    description = (
        _clean(_lead_value(lead, "description", "need_description"))
        or "Not provided"
    )

    reference = (
        _clean(lead.get("lead_reference"))
        or _lead_reference()
    )

    values = (
        reference,
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
        _clean(_lead_value(lead, "budget", "budget_range")),
        _clean(lead.get("timeline")),
        _clean(lead.get("status")) or "new",
        _clean(lead.get("priority")) or "unassessed",
        lead.get("assigned_owner_id"),
        lead.get("duplicate_of_lead_id"),
        bool(lead.get("consent_to_contact", False))
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
                    assigned_owner_id,
                    duplicate_of_lead_id,
                    consent_to_contact
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s, 'Not provided'),
                    %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
            """, values)

            lead_id = cur.fetchone()["id"]

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
            """, (
                lead_id,
                "lead_created",
                "completed",
                f"Lead {reference} was created.",
                Json({"lead_reference": reference}),
                "lead_intake"
            ))

    return lead_id


# ============================================================
# LEAD RETRIEVAL
# ============================================================

def get_leads(limit=1000):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
                    so.full_name AS assigned_owner_name,
                    so.email AS assigned_owner_email
                FROM leads l
                LEFT JOIN sales_owners so
                    ON so.id = l.assigned_owner_id
                ORDER BY l.created_at DESC
                LIMIT %s
            """, (limit,))

            rows = cur.fetchall()

    return [dict(row) for row in rows]


def get_lead_by_id(lead_id):
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


def update_lead_status(lead_id, status):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE leads
                SET status = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (status, lead_id))

            return cur.rowcount > 0


# ============================================================
# AI QUALIFICATION RESULTS
# ============================================================

def save_qualification_result(
    lead_id,
    result=None,
    score=None,
    category=None,
    reasoning=None,
    missing_information=None,
    recommended_next_action=None,
    human_review_required=True,
    model_name="Groq"
):
    if isinstance(result, dict):
        data = result
    else:
        data = {
            "score": score,
            "category": category,
            "reasoning": reasoning,
            "missing_information": missing_information or [],
            "recommended_next_action": recommended_next_action,
            "human_review_required": human_review_required,
            "model_name": model_name
        }

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
                data.get("model_name", "Groq"),
                int(data.get("score", 0)),
                data.get("category", "needs_review"),
                data.get("reasoning", ""),
                Json(data.get("missing_information", [])),
                data.get("recommended_next_action", ""),
                bool(data.get("human_review_required", True))
            ))

            result_id = cur.fetchone()["id"]

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
            """, (
                lead_id,
                "lead_ai_qualified",
                "completed",
                f"AI qualification saved: {data.get('score', 0)}/100.",
                Json({
                    "score": data.get("score"),
                    "category": data.get("category"),
                    "priority": data.get("priority")
                }),
                "groq_ai_qualification"
            ))

    return result_id


def update_lead_qualification(
    lead_id,
    category=None,
    priority=None,
    **kwargs
):
    if category is None:
        category = kwargs.get("category")

    if priority is None:
        priority = kwargs.get("priority")

    status = (
        "needs_review"
        if category == "needs_review"
        else "qualified"
    )

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE leads
                SET priority = COALESCE(%s, priority),
                    status = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, (priority, status, lead_id))

            return cur.rowcount > 0


def get_qualification_results(lead_id=None, limit=200):
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
            l.company
        FROM qualification_results qr
        LEFT JOIN leads l ON l.id = qr.lead_id
    """

    params = []

    if lead_id is not None:
        sql += " WHERE qr.lead_id = %s"
        params.append(lead_id)

    sql += " ORDER BY qr.created_at DESC LIMIT %s"
    params.append(limit)

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    return [dict(row) for row in rows]


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

            return cur.fetchone()["id"]


def get_workflow_events(limit=250):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (limit,))

            rows = cur.fetchall()

    return [dict(row) for row in rows]


# ============================================================
# SALES OWNER MANAGEMENT
# ============================================================

def get_sales_owners(available_only=False):
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
            rows = cur.fetchall()

    return [dict(row) for row in rows]


def create_sales_owner(
    full_name,
    email,
    specialization,
    active_lead_limit=20,
    is_available=True
):
    full_name = _clean(full_name)
    email = _normal_text(email)
    specialization = _clean(specialization) or "General"

    if not full_name:
        raise ValueError("Sales owner name is required.")

    if not email or "@" not in email:
        raise ValueError("A valid owner email is required.")

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sales_owners (
                    full_name,
                    email,
                    specialization,
                    is_available,
                    active_lead_limit
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                full_name,
                email,
                specialization,
                bool(is_available),
                max(1, int(active_lead_limit))
            ))

            owner_id = cur.fetchone()["id"]

            cur.execute("""
                INSERT INTO workflow_events (
                    lead_id,
                    event_type,
                    event_status,
                    message,
                    details,
                    actor
                )
                VALUES (NULL, %s, %s, %s, %s, %s)
            """, (
                "sales_owner_created",
                "completed",
                f"Sales owner {full_name} was added to the roster.",
                Json({
                    "owner_id": owner_id,
                    "specialization": specialization
                }),
                "sales_admin"
            ))

    return owner_id


def update_sales_owner_availability(owner_id, is_available):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE sales_owners
                SET is_available = %s
                WHERE id = %s
            """, (bool(is_available), owner_id))

            return cur.rowcount > 0


def get_owner_workloads():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    so.id,
                    so.full_name,
                    so.email,
                    so.specialization,
                    so.is_available,
                    so.active_lead_limit,
                    COUNT(
                        CASE
                            WHEN l.id IS NOT NULL
                             AND LOWER(COALESCE(l.status, '')) NOT IN (
                                'converted',
                                'disqualified',
                                'closed_won',
                                'closed_lost',
                                'duplicate'
                             )
                            THEN 1
                        END
                    ) AS active_leads
                FROM sales_owners so
                LEFT JOIN leads l
                    ON l.assigned_owner_id = so.id
                GROUP BY
                    so.id,
                    so.full_name,
                    so.email,
                    so.specialization,
                    so.is_available,
                    so.active_lead_limit
                ORDER BY so.full_name
            """)

            rows = cur.fetchall()

    result = []

    for row in rows:
        item = dict(row)

        item["active_leads"] = int(item["active_leads"] or 0)
        item["active_lead_limit"] = int(
            item["active_lead_limit"] or 0
        )

        item["remaining_capacity"] = max(
            0,
            item["active_lead_limit"] - item["active_leads"]
        )

        result.append(item)

    return result


# ============================================================
# INTELLIGENT OWNER ASSIGNMENT
# ============================================================

def _specialization_match(specialization, lead):
    """
    Match an owner's specialization against the lead's industry
    and company size.

    Examples:
    - Biotechnology
    - Healthcare
    - Enterprise
    - SMB
    - General
    """

    spec = _normal_text(specialization) or "general"

    industry = _normal_text(lead.get("industry")) or ""
    company_size = _normal_text(lead.get("company_size")) or ""

    lead_description = f"{industry} {company_size}"

    if spec in {
        "general",
        "all",
        "any",
        "all industries",
        "*"
    }:
        return True

    tokens = [
        token.strip()
        for token in re.split(r"[,;/|]+", spec)
        if token.strip()
    ]

    if not tokens:
        tokens = [spec]

    return any(token in lead_description for token in tokens)


def _assignment_event(
    cur,
    lead_id,
    event_type,
    status,
    message,
    details
):
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
    """, (
        lead_id,
        event_type,
        status,
        message,
        Json(details or {}),
        "intelligent_assignment"
    ))


def assign_lead_automatically(lead_id):
    """
    Automatic assignment rules:

    1. Exclude unavailable owners.
    2. Exclude owners at their active-lead limit.
    3. Prefer a specialization match.
    4. Among eligible owners, select the lowest workload ratio.
    5. Record the decision in workflow_events.
    """

    with _connect() as conn:
        with conn.cursor() as cur:

            # Lock owner rows during selection.
            cur.execute("""
                SELECT
                    id,
                    full_name,
                    email,
                    specialization,
                    is_available,
                    active_lead_limit
                FROM sales_owners
                ORDER BY id
                FOR UPDATE
            """)

            owners = [
                dict(row)
                for row in cur.fetchall()
            ]

            cur.execute("""
                SELECT
                    id,
                    lead_reference,
                    full_name AS contact_name,
                    company,
                    industry,
                    company_size,
                    priority,
                    status,
                    assigned_owner_id
                FROM leads
                WHERE id = %s
                FOR UPDATE
            """, (lead_id,))

            lead = cur.fetchone()

            if not lead:
                raise ValueError("Lead was not found.")

            if lead.get("assigned_owner_id") is not None:
                cur.execute("""
                    SELECT full_name
                    FROM sales_owners
                    WHERE id = %s
                """, (lead["assigned_owner_id"],))

                existing = cur.fetchone()

                return {
                    "assigned": True,
                    "already_assigned": True,
                    "owner_name": (
                        existing["full_name"]
                        if existing else "Existing owner"
                    ),
                    "message": "This lead already has an assigned owner."
                }

            candidates = []

            for owner in owners:

                if not owner.get("is_available"):
                    continue

                capacity = int(
                    owner.get("active_lead_limit") or 0
                )

                if capacity <= 0:
                    continue

                cur.execute("""
                    SELECT COUNT(*) AS active_count
                    FROM leads
                    WHERE assigned_owner_id = %s
                      AND LOWER(COALESCE(status, '')) NOT IN (
                          'converted',
                          'disqualified',
                          'closed_won',
                          'closed_lost',
                          'duplicate'
                      )
                """, (owner["id"],))

                active_count = int(
                    cur.fetchone()["active_count"]
                )

                if active_count >= capacity:
                    continue

                specialist = _specialization_match(
                    owner.get("specialization"),
                    lead
                )

                utilization = active_count / capacity

                candidates.append({
                    **owner,
                    "active_count": active_count,
                    "capacity": capacity,
                    "specialist_match": specialist,
                    "utilization": utilization
                })

            if not candidates:
                message = (
                    "No available sales owner has remaining capacity. "
                    "Lead remains unassigned."
                )

                _assignment_event(
                    cur,
                    lead_id,
                    "owner_assignment_unavailable",
                    "needs_review",
                    message,
                    {
                        "lead_reference": lead["lead_reference"],
                        "priority": lead.get("priority"),
                        "reason": (
                            "No available owner with remaining capacity"
                        )
                    }
                )

                return {
                    "assigned": False,
                    "owner_name": None,
                    "message": message
                }

            specialists = [
                owner
                for owner in candidates
                if owner["specialist_match"]
            ]

            pool = specialists if specialists else candidates

            selected = sorted(
                pool,
                key=lambda owner: (
                    owner["utilization"],
                    owner["active_count"],
                    int(owner["id"])
                )
            )[0]

            if selected["specialist_match"]:
                specialization_reason = (
                    "specialization match: "
                    + str(selected.get("specialization"))
                )
            else:
                specialization_reason = (
                    "no exact specialization match; "
                    "selected an eligible available owner"
                )

            reason = (
                specialization_reason
                + f"; workload {selected['active_count']}/"
                + f"{selected['capacity']}"
                + f"; lead priority {lead.get('priority') or 'unassessed'}"
            )

            cur.execute("""
                UPDATE leads
                SET assigned_owner_id = %s,
                    status = CASE
                        WHEN LOWER(COALESCE(status, ''))
                            IN ('new', 'qualified')
                        THEN 'assigned'
                        ELSE status
                    END,
                    updated_at = NOW()
                WHERE id = %s
            """, (selected["id"], lead_id))

            _assignment_event(
                cur,
                lead_id,
                "owner_assigned",
                "completed",
                f"Lead assigned to {selected['full_name']}.",
                {
                    "lead_reference": lead["lead_reference"],
                    "owner_id": selected["id"],
                    "owner_name": selected["full_name"],
                    "specialization": selected.get("specialization"),
                    "active_leads_before_assignment": selected["active_count"],
                    "active_lead_limit": selected["capacity"],
                    "priority": lead.get("priority"),
                    "assignment_reason": reason
                }
            )

            return {
                "assigned": True,
                "already_assigned": False,
                "owner_id": selected["id"],
                "owner_name": selected["full_name"],
                "reason": reason,
                "message": (
                    f"Successfully assigned to {selected['full_name']}."
                )
            }


def assign_lead_owner(lead_id, owner_id):
    """Manually assign a lead while enforcing owner availability and capacity."""

    with _connect() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    id,
                    full_name,
                    is_available,
                    active_lead_limit
                FROM sales_owners
                WHERE id = %s
                FOR UPDATE
            """, (owner_id,))

            owner = cur.fetchone()

            if not owner:
                raise ValueError("Selected sales owner was not found.")

            if not owner["is_available"]:
                raise ValueError(
                    "This sales owner is currently unavailable."
                )

            cur.execute("""
                SELECT
                    id,
                    lead_reference,
                    assigned_owner_id,
                    status
                FROM leads
                WHERE id = %s
                FOR UPDATE
            """, (lead_id,))

            lead = cur.fetchone()

            if not lead:
                raise ValueError("Lead was not found.")

            if lead["assigned_owner_id"] is not None:
                raise ValueError(
                    "This lead is already assigned. "
                    "Unassign it before changing the owner."
                )

            cur.execute("""
                SELECT COUNT(*) AS active_count
                FROM leads
                WHERE assigned_owner_id = %s
                  AND LOWER(COALESCE(status, '')) NOT IN (
                      'converted',
                      'disqualified',
                      'closed_won',
                      'closed_lost',
                      'duplicate'
                  )
            """, (owner_id,))

            active_count = int(
                cur.fetchone()["active_count"]
            )

            capacity = int(
                owner["active_lead_limit"] or 0
            )

            if capacity <= 0 or active_count >= capacity:
                raise ValueError(
                    "This sales owner has reached their active-lead limit."
                )

            cur.execute("""
                UPDATE leads
                SET assigned_owner_id = %s,
                    status = CASE
                        WHEN LOWER(COALESCE(status, ''))
                            IN ('new', 'qualified')
                        THEN 'assigned'
                        ELSE status
                    END,
                    updated_at = NOW()
                WHERE id = %s
            """, (owner_id, lead_id))

            _assignment_event(
                cur,
                lead_id,
                "owner_assigned_manually",
                "completed",
                f"Lead manually assigned to {owner['full_name']}.",
                {
                    "lead_reference": lead["lead_reference"],
                    "owner_id": owner_id,
                    "owner_name": owner["full_name"],
                    "active_leads_before_assignment": active_count,
                    "active_lead_limit": capacity,
                    "assignment_reason": (
                        "Manual assignment by administrator"
                    )
                }
            )

    return True


def unassign_lead_owner(lead_id):
    """Remove an assignment and return the lead to the unassigned queue."""

    with _connect() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    l.id,
                    l.lead_reference,
                    l.assigned_owner_id,
                    so.full_name AS owner_name
                FROM leads l
                LEFT JOIN sales_owners so
                    ON so.id = l.assigned_owner_id
                WHERE l.id = %s
                FOR UPDATE OF l
            """, (lead_id,))

            lead = cur.fetchone()

            if not lead:
                raise ValueError("Lead was not found.")

            if lead["assigned_owner_id"] is None:
                return False

            previous_owner_id = lead["assigned_owner_id"]
            previous_owner_name = lead.get("owner_name")

            cur.execute("""
                UPDATE leads
                SET assigned_owner_id = NULL,
                    status = CASE
                        WHEN LOWER(COALESCE(status, '')) = 'assigned'
                        THEN 'qualified'
                        ELSE status
                    END,
                    updated_at = NOW()
                WHERE id = %s
            """, (lead_id,))

            _assignment_event(
                cur,
                lead_id,
                "owner_unassigned",
                "completed",
                "Lead returned to the unassigned queue.",
                {
                    "lead_reference": lead["lead_reference"],
                    "previous_owner_id": previous_owner_id,
                    "previous_owner_name": previous_owner_name
                }
            )

    return True


# ============================================================
# EMAIL DRAFT FUNCTIONS
# Used in Step 7.
# ============================================================

def save_email_draft(
    lead_id,
    recipient_email,
    subject,
    body,
    draft_status="draft"
):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_drafts (
                    lead_id,
                    recipient_email,
                    subject,
                    body,
                    draft_status
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                lead_id,
                recipient_email,
                subject,
                body,
                draft_status
            ))

            return cur.fetchone()["id"]


def get_email_drafts(lead_id=None, limit=200):
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
            rows = cur.fetchall()

    return [dict(row) for row in rows]

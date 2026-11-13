
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from database import (
    get_leads,
    get_owner_workloads,
    get_email_drafts,
    get_workflow_events,
    get_qualification_results,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="LeadFlow AI | Dashboard & Audit",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# STYLING
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(
                circle at 10% 5%,
                rgba(91, 55, 145, 0.18),
                transparent 30%
            ),
            linear-gradient(
                135deg,
                #0b1020 0%,
                #10172a 55%,
                #111827 100%
            );
        color: #f1f5f9;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(
            180deg,
            #111827 0%,
            #17152d 100%
        );
        border-right: 1px solid rgba(148, 163, 184, 0.15);
    }

    [data-testid="stSidebar"] * {
        color: #e2e8f0;
    }

    h1, h2, h3, h4 {
        color: #f8fafc !important;
    }

    div[data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.78);
        border: 1px solid rgba(148, 163, 184, 0.18);
        padding: 16px;
        border-radius: 14px;
    }

    div[data-testid="stMetricLabel"] {
        color: #cbd5e1 !important;
    }

    div[data-testid="stMetricValue"] {
        color: #f8fafc !important;
    }

    .hero {
        padding: 25px 28px;
        border-radius: 18px;
        background: linear-gradient(
            120deg,
            rgba(91, 55, 145, .35),
            rgba(30, 64, 175, .22)
        );
        border: 1px solid rgba(167, 139, 250, .25);
        margin-bottom: 22px;
    }

    .hero p {
        color: #cbd5e1;
        margin-bottom: 0;
    }

    .muted {
        color: #aab6ca;
        font-size: 0.9rem;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, .18);
        border-radius: 12px;
        overflow: hidden;
    }

    .section-note {
        color: #aab6ca;
        font-size: 0.85rem;
        margin-top: -8px;
    }

    .detail-card {
        background: rgba(30, 41, 59, 0.65);
        border: 1px solid rgba(148, 163, 184, 0.20);
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
    }

    .detail-label {
        color: #aab6ca;
        font-size: 0.82rem;
        margin-bottom: 5px;
    }

    .detail-value {
        color: #f8fafc;
        font-size: 1rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HELPERS
# ============================================================

def normalize_category(value):
    value = str(value or "").strip().lower()
    return value.replace(" ", "_").replace("-", "_")


def humanize_value(value):
    if value is None:
        return "—"

    return str(value).replace("_", " ").replace("-", " ").title()


def format_datetime(value):
    if not value:
        return "—"

    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")

    return str(value)


def safe_json(value):
    if value is None:
        return {}

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {"information": value}

    return {"information": str(value)}


def make_dataframe(rows):
    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows)


def show_empty(message):
    st.info(message)


def detail_metric(label, value):
    st.metric(label, value if value is not None else "—")


# ============================================================
# EVENT DETAIL FORMATTERS
# ============================================================

def show_qualification_details(details):

    st.subheader("AI Qualification Result")

    score = details.get("score")
    category = details.get("category")
    reasoning = details.get("reasoning")
    missing_information = details.get("missing_information", [])
    human_review = details.get("human_review_required")
    next_action = details.get("recommended_next_action")

    col1, col2, col3 = st.columns(3)

    with col1:
        detail_metric(
            "Qualification Score",
            f"{score}/100" if score is not None else "—",
        )

    with col2:
        detail_metric(
            "Qualification Category",
            humanize_value(category) if category else "—",
        )

    with col3:
        if human_review is True:
            review_label = "Required"
        elif human_review is False:
            review_label = "Not Required"
        else:
            review_label = "Not Specified"

        detail_metric("Human Review", review_label)

    st.markdown("#### AI Reasoning")

    if reasoning:
        st.info(reasoning)
    else:
        st.write("No reasoning was stored.")

    st.markdown("#### Missing Information")

    if isinstance(missing_information, list) and missing_information:
        for item in missing_information:
            st.markdown(f"- {humanize_value(item)}")
    elif missing_information:
        st.write(missing_information)
    else:
        st.success("No missing information was recorded.")

    st.markdown("#### Recommended Next Action")

    if next_action:
        st.success(next_action)
    else:
        st.write("No next action was recorded.")


def show_agent_email_draft_created(details):

    st.subheader("AI Email Draft Generation")

    col1, col2 = st.columns(2)

    with col1:
        detail_metric(
            "Email Draft ID",
            details.get("email_draft_id"),
        )

        detail_metric(
            "Email Sent",
            "Yes" if details.get("email_sent") is True else "No",
        )

    with col2:
        detail_metric(
            "Approval Required",
            "Yes" if details.get("approval_required") else "No",
        )

    st.markdown("#### Email Subject")

    st.info(details.get("subject") or "No subject recorded.")

    st.caption(
        "This event records draft generation. It does not mean an email was sent."
    )


def show_email_draft_created(details):

    st.subheader("Email Draft Created")

    col1, col2, col3 = st.columns(3)

    with col1:
        detail_metric(
            "Draft ID",
            details.get("email_draft_id"),
        )

    with col2:
        detail_metric(
            "Draft Status",
            humanize_value(details.get("draft_status")),
        )

    with col3:
        detail_metric(
            "Recipient",
            details.get("recipient_email"),
        )

    st.markdown("#### Email Subject")

    st.info(details.get("subject") or "No subject recorded.")

    st.caption(
        "An email draft was created and is awaiting the applicable review process."
    )


def show_owner_assignment(details):

    st.subheader("Automatic Sales Owner Assignment")

    col1, col2, col3 = st.columns(3)

    with col1:
        detail_metric(
            "Assigned Owner",
            details.get("owner_name"),
        )

    with col2:
        detail_metric(
            "Owner ID",
            details.get("owner_id"),
        )

    with col3:
        detail_metric(
            "Specialization",
            humanize_value(details.get("specialization")),
        )

    st.markdown("#### Owner Workload")

    workload_col1, workload_col2, workload_col3 = st.columns(3)

    with workload_col1:
        detail_metric(
            "Active Leads",
            details.get("active_leads"),
        )

    with workload_col2:
        detail_metric(
            "Maximum Lead Capacity",
            details.get("active_lead_limit"),
        )

    with workload_col3:
        active = details.get("active_leads")
        limit = details.get("active_lead_limit")

        if active is not None and limit is not None:
            remaining = max(int(limit) - int(active), 0)
        else:
            remaining = None

        detail_metric("Remaining Capacity", remaining)


def show_lead_created(details):

    st.subheader("Lead Created by Agent Workflow")

    col1, col2 = st.columns(2)

    with col1:
        detail_metric(
            "Workflow",
            details.get("workflow"),
        )

    with col2:
        detail_metric(
            "Lead Reference",
            details.get("lead_reference"),
        )

    st.success(
        "The lead creation event was successfully recorded in the workflow history."
    )


def show_email_skipped(details):

    st.subheader("Email Draft Skipped")

    reason = details.get("reason")

    if reason == "consent_not_recorded":
        st.warning(
            "The email draft was not generated because contact consent "
            "was not recorded for this lead."
        )
    else:
        st.info(
            f"Email generation was skipped. Reason: {humanize_value(reason)}"
        )

    col1, col2 = st.columns(2)

    with col1:
        detail_metric(
            "Skip Reason",
            humanize_value(reason),
        )

    with col2:
        detail_metric(
            "Draft Created",
            "Yes" if details.get("draft_created") is True else "No",
        )


def show_email_approved(details):

    st.subheader("Email Draft Approved")

    col1, col2 = st.columns(2)

    with col1:
        detail_metric(
            "Email Draft ID",
            details.get("email_draft_id"),
        )

    with col2:
        detail_metric(
            "Recipient",
            details.get("recipient_email"),
        )

    st.markdown("#### Approved Email Subject")

    st.info(details.get("subject") or "No subject recorded.")

    st.success(
        "The email draft approval action was recorded."
    )


def show_email_updated(details):

    st.subheader("Email Draft Updated")

    col1, col2 = st.columns(2)

    with col1:
        detail_metric(
            "Email Draft ID",
            details.get("email_draft_id"),
        )

    with col2:
        detail_metric(
            "Current Draft Status",
            humanize_value(details.get("draft_status")),
        )

    st.markdown("#### Email Subject")

    st.info(details.get("subject") or "No subject recorded.")

    st.markdown("#### Recipient")

    st.write(details.get("recipient_email") or "—")


def show_workflow_failure_details(details):

    st.subheader("Workflow Failure Diagnostics")

    col1, col2, col3 = st.columns(3)

    with col1:
        detail_metric(
            "Failure Stage",
            humanize_value(details.get("failure_stage")),
        )

    with col2:
        detail_metric(
            "Failure Classification",
            humanize_value(details.get("failure_classification")),
        )

    with col3:
        detail_metric(
            "Underlying Classification",
            humanize_value(
                details.get("underlying_failure_classification")
            ),
        )

    st.markdown("#### Technical Information")

    technical_col1, technical_col2 = st.columns(2)

    with technical_col1:
        detail_metric(
            "Exception Type",
            details.get("failure_exception_type"),
        )

        detail_metric(
            "Error Code",
            details.get("failure_error_code") or "Not available",
        )

    with technical_col2:
        detail_metric(
            "Retryable",
            "Yes" if details.get("failure_retryable") is True else "No",
        )

        lead_creation_unknown = (
            details.get("lead_creation_state_known") is False
            or details.get("lead_creation_state") == "unknown"
        )
    
        if lead_creation_unknown:
            lead_creation_value = "Unknown"
        elif details.get("lead_created_before_failure") is True:
            lead_creation_value = "Yes"
        elif details.get("lead_created_before_failure") is False:
            lead_creation_value = "No"
        else:
            lead_creation_value = "Not recorded"
    
        detail_metric(
            "Lead Created Before Failure",
            lead_creation_value,
        )

    st.markdown("#### Failure Message")

    failure_message = details.get("failure_message")

    if failure_message:
        st.error(failure_message)
    else:
        st.info("No technical failure message was stored.")

    st.markdown("#### Additional Recovery Information")

    detail_metric(
        "Email Draft Created",
        (
            "Yes"
            if details.get("draft_created") is True
            else "No"
            if details.get("draft_created") is False
            else "Not recorded"
        ),
    )

    detail_metric(
        "Email Draft ID",
        details.get("email_draft_id") or "Not available",
    )

    detail_metric(
        "Email Sent",
        "Yes" if details.get("email_sent") is True else "No",
    )

    if details.get("lead_creation_state_known") is False:
        st.warning(
            "The lead creation state is unknown because the workflow "
            "failed at the top-level execution handler."
        )

    elif details.get("lead_creation_state") == "unknown":
        st.warning(
            "The workflow could not confirm whether lead creation "
            "completed before the failure."
        )

def show_generic_details(details):

    st.subheader("Additional Event Information")

    if not details:
        st.info("No additional event details were recorded.")
        return

    if isinstance(details, dict):
        for key, value in details.items():
            st.markdown(f"**{humanize_value(key)}**")

            if isinstance(value, (dict, list)):
                st.write(value)
            else:
                st.write(value)

    else:
        st.write(details)


def show_event_details(event):

    details = safe_json(event.get("details"))
    event_type = str(event.get("event_type") or "").strip()

    if not details:
        st.info("No additional details were stored for this event.")
        return

    if not isinstance(details, dict):
        show_generic_details(details)
        return

    # Match the event type to its corresponding readable formatter.

    event_formatters = {
        "agent_ai_qualification_completed": show_qualification_details,
        "agent_email_draft_created": show_agent_email_draft_created,
        "email_draft_created": show_email_draft_created,
        "automatic_owner_assignment": show_owner_assignment,
        "agent_workflow_lead_created": show_lead_created,
        "agent_email_skipped_no_consent": show_email_skipped,
        "email_draft_approved": show_email_approved,
        "email_draft_updated": show_email_updated,
        "agent_workflow_failure_detected": show_workflow_failure_details,
    }

    formatter = event_formatters.get(event_type)

    if formatter:
        formatter(details)

    else:
        st.info(
            "This event type does not yet have a dedicated display format. "
            "Its stored fields are shown below."
        )
        show_generic_details(details)


# ============================================================
# DATA LOADING
# ============================================================

@st.cache_data(ttl=30, show_spinner=False)
def load_dashboard_data():

    leads = get_leads()
    owners = get_owner_workloads()
    drafts = get_email_drafts()
    events = get_workflow_events()

    qualification_map = {}

    for lead in leads:

        lead_id = lead.get("id")

        if lead_id is None:
            continue

        results = get_qualification_results(lead_id)

        if results:
            qualification_map[lead_id] = results[0]

    return {
        "leads": leads,
        "owners": owners,
        "drafts": drafts,
        "events": events,
        "qualifications": qualification_map,
    }


# ============================================================
# HEADER
# ============================================================

st.title("📊 Dashboard & Audit Center")

st.markdown(
    """
    <div class="hero">
        <h2>LeadFlow AI Command Center</h2>
        <p>
            Monitor your sales pipeline, understand lead quality,
            track owner capacity, and inspect the complete workflow
            activity recorded in Neon PostgreSQL.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

header_col1, header_col2 = st.columns([4, 1])

with header_col1:
    st.caption(
        f"Last opened: {datetime.now().strftime('%d %b %Y, %I:%M %p')}"
    )

with header_col2:
    if st.button(
        "↻ Refresh data",
        use_container_width=True,
    ):
        load_dashboard_data.clear()
        st.rerun()


# ============================================================
# LOAD DATABASE RECORDS
# ============================================================

try:

    with st.spinner("Loading dashboard information from Neon..."):
        data = load_dashboard_data()

except Exception as exc:

    st.error("Unable to load dashboard information from the database.")
    st.exception(exc)
    st.stop()


leads = data["leads"]
owners = data["owners"]
drafts = data["drafts"]
events = data["events"]
qualifications = data["qualifications"]


# ============================================================
# CALCULATE METRICS
# ============================================================

total_leads = len(leads)

assigned_leads = [
    lead for lead in leads
    if lead.get("assigned_owner_id") is not None
]

unassigned_leads = [
    lead for lead in leads
    if lead.get("assigned_owner_id") is None
]

active_leads = [
    lead for lead in leads
    if str(lead.get("status") or "").lower()
    not in ("closed", "won", "lost", "disqualified")
]

qualified_count = 0
needs_review_count = 0

category_counts = {
    "high_fit": 0,
    "medium_fit": 0,
    "low_fit": 0,
    "needs_review": 0,
}

for lead_id, result in qualifications.items():

    category = normalize_category(result.get("category"))

    if category in category_counts:
        category_counts[category] += 1

    if category in ("high_fit", "medium_fit", "low_fit"):
        qualified_count += 1

    if category == "needs_review":
        needs_review_count += 1


approved_drafts = [
    draft for draft in drafts
    if str(draft.get("draft_status") or "").lower() == "approved"
]

pending_drafts = [
    draft for draft in drafts
    if str(draft.get("draft_status") or "").lower()
    in ("draft", "pending_review")
]

failed_events = [
    event for event in events
    if str(event.get("event_status") or "").lower()
    in ("failed", "error")
]


# ============================================================
# SECTION 1 — KEY PERFORMANCE INDICATORS
# ============================================================

st.header("Business Overview")

st.caption(
    "Live record counts calculated from your existing database."
)

metric_row1 = st.columns(4)

metric_row1[0].metric("Total Leads", total_leads)
metric_row1[1].metric("Active Leads", len(active_leads))
metric_row1[2].metric("Assigned Leads", len(assigned_leads))
metric_row1[3].metric("Unassigned Leads", len(unassigned_leads))

metric_row2 = st.columns(4)

metric_row2[0].metric("AI Qualified", qualified_count)
metric_row2[1].metric("Needs Review", needs_review_count)
metric_row2[2].metric("Approved Drafts", len(approved_drafts))
metric_row2[3].metric("Workflow Errors", len(failed_events))

st.divider()


# ============================================================
# SECTION 2 — LEAD PIPELINE
# ============================================================

st.header("Lead Pipeline")

st.caption(
    "Understand how leads are distributed across their current statuses."
)

status_counts = {}

for lead in leads:

    status = str(lead.get("status") or "unknown").strip().lower()
    status_counts[status] = status_counts.get(status, 0) + 1

priority_counts = {}

for lead in leads:

    priority = str(
        lead.get("priority") or "unassessed"
    ).strip().lower()

    priority_counts[priority] = priority_counts.get(priority, 0) + 1


pipeline_col1, pipeline_col2 = st.columns(2)

with pipeline_col1:

    st.subheader("Leads by Status")

    if status_counts:

        status_df = pd.DataFrame(
            [
                {
                    "Status": key.replace("_", " ").title(),
                    "Leads": value,
                }
                for key, value in sorted(status_counts.items())
            ]
        )

        st.bar_chart(
            status_df,
            x="Status",
            y="Leads",
            use_container_width=True,
        )

        st.dataframe(
            status_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        show_empty("No lead status information is available.")


with pipeline_col2:

    st.subheader("Leads by Priority")

    if priority_counts:

        priority_df = pd.DataFrame(
            [
                {
                    "Priority": key.replace("_", " ").title(),
                    "Leads": value,
                }
                for key, value in sorted(priority_counts.items())
            ]
        )

        st.bar_chart(
            priority_df,
            x="Priority",
            y="Leads",
            use_container_width=True,
        )

        st.dataframe(
            priority_df,
            use_container_width=True,
            hide_index=True,
        )

    else:
        show_empty("No priority information is available.")


st.divider()


# ============================================================
# SECTION 3 — AI QUALIFICATION ANALYTICS
# ============================================================

st.header("AI Qualification Analytics")

st.caption(
    "Latest saved qualification result for each lead."
)

qualification_col1, qualification_col2 = st.columns(2)

with qualification_col1:

    st.subheader("Qualification Categories")

    qualification_labels = {
        "high_fit": "High Fit",
        "medium_fit": "Medium Fit",
        "low_fit": "Low Fit",
        "needs_review": "Needs Review",
    }

    qualification_df = pd.DataFrame(
        [
            {
                "Category": qualification_labels[key],
                "Leads": value,
            }
            for key, value in category_counts.items()
        ]
    )

    if sum(category_counts.values()) > 0:

        st.bar_chart(
            qualification_df,
            x="Category",
            y="Leads",
            use_container_width=True,
        )

    else:
        show_empty(
            "No AI qualification results have been saved yet."
        )


with qualification_col2:

    st.subheader("Latest Qualification Records")

    qualification_rows = []

    for lead in leads:

        result = qualifications.get(lead.get("id"))

        if not result:
            continue

        qualification_rows.append(
            {
                "Lead Reference": lead.get("lead_reference"),
                "Contact": lead.get("contact_name"),
                "Company": lead.get("company"),
                "Score": result.get("score"),
                "Category": humanize_value(result.get("category")),
                "Human Review": (
                    "Yes"
                    if result.get("human_review_required")
                    else "No"
                ),
            }
        )

    if qualification_rows:

        st.dataframe(
            qualification_rows,
            use_container_width=True,
            hide_index=True,
        )

    else:
        show_empty("No qualification records are available.")


st.divider()


# ============================================================
# SECTION 4 — SALES OWNER PERFORMANCE
# ============================================================

st.header("Sales Team Performance")

st.caption(
    "Monitor assigned workload, availability, and remaining capacity."
)

if owners:

    owner_rows = []

    for owner in owners:

        active = int(owner.get("active_leads") or 0)
        capacity = int(owner.get("active_lead_limit") or 0)

        remaining = max(capacity - active, 0)

        utilization = (
            round((active / capacity) * 100, 1)
            if capacity > 0
            else 0
        )

        owner_rows.append(
            {
                "Sales Owner": owner.get("full_name"),
                "Specialization": owner.get("specialization"),
                "Available": (
                    "Yes"
                    if owner.get("is_available")
                    else "No"
                ),
                "Active Leads": active,
                "Capacity": capacity,
                "Remaining Capacity": remaining,
                "Utilization (%)": utilization,
            }
        )

    owner_df = pd.DataFrame(owner_rows)

    st.dataframe(
        owner_df,
        use_container_width=True,
        hide_index=True,
    )

    owner_chart_df = owner_df[
        ["Sales Owner", "Active Leads", "Remaining Capacity"]
    ].set_index("Sales Owner")

    st.subheader("Owner Workload Comparison")

    st.bar_chart(
        owner_chart_df,
        use_container_width=True,
    )

else:

    show_empty(
        "No sales owners have been added yet. "
        "Add owners in Assignment & Follow-up."
    )


st.divider()


# ============================================================
# SECTION 5 — RECENT LEADS
# ============================================================

st.header("Recent Leads")

if leads:

    recent_leads = []

    for lead in leads[:10]:

        qualification = qualifications.get(lead.get("id"))

        recent_leads.append(
            {
                "Reference": lead.get("lead_reference"),
                "Contact": lead.get("contact_name"),
                "Company": lead.get("company"),
                "Status": lead.get("status"),
                "Priority": lead.get("priority"),
                "Qualification": (
                    humanize_value(qualification.get("category"))
                    if qualification
                    else "Not assessed"
                ),
                "Owner": lead.get("assigned_owner") or "Unassigned",
                "Created": format_datetime(lead.get("created_at")),
            }
        )

    st.dataframe(
        recent_leads,
        use_container_width=True,
        hide_index=True,
    )

else:

    show_empty("No leads have been submitted yet.")


st.divider()


# ============================================================
# SECTION 6 — RECENT WORKFLOW ACTIVITY
# ============================================================

st.header("Recent Workflow Activity")

st.caption(
    "The latest events recorded by LeadFlow AI agents and application actions."
)

if events:

    recent_events = []

    for event in events[:12]:

        recent_events.append(
            {
                "Time": format_datetime(event.get("created_at")),
                "Lead": event.get("lead_reference") or "System",
                "Contact": event.get("contact_name") or "—",
                "Event": event.get("event_type"),
                "Status": event.get("event_status"),
                "Message": event.get("message"),
                "Actor": event.get("actor"),
            }
        )

    st.dataframe(
        recent_events,
        use_container_width=True,
        hide_index=True,
    )

else:

    show_empty("No workflow events have been recorded yet.")


st.divider()


# ============================================================
# SECTION 7 — AUDIT EXPLORER
# ============================================================

st.header("Workflow Audit Explorer")

st.caption(
    "Search and inspect workflow events, including readable stored event details."
)

if not events:

    show_empty(
        "No audit events are available. Run a lead workflow to generate events."
    )

else:

    event_types = sorted(
        {
            str(event.get("event_type") or "unknown")
            for event in events
        }
    )

    event_statuses = sorted(
        {
            str(event.get("event_status") or "unknown")
            for event in events
        }
    )

    filter_col1, filter_col2, filter_col3 = st.columns(3)

    with filter_col1:

        selected_event_type = st.selectbox(
            "Event type",
            ["All event types"] + event_types,
        )

    with filter_col2:

        selected_event_status = st.selectbox(
            "Event status",
            ["All statuses"] + event_statuses,
        )

    with filter_col3:

        audit_search = st.text_input(
            "Search audit history",
            placeholder="Lead, contact, event, actor...",
        )

    filtered_events = events

    if selected_event_type != "All event types":

        filtered_events = [
            event for event in filtered_events
            if str(event.get("event_type") or "unknown")
            == selected_event_type
        ]

    if selected_event_status != "All statuses":

        filtered_events = [
            event for event in filtered_events
            if str(event.get("event_status") or "unknown")
            == selected_event_status
        ]

    if audit_search.strip():

        term = audit_search.strip().lower()

        filtered_events = [
            event for event in filtered_events
            if term in " ".join(
                [
                    str(event.get("lead_reference") or ""),
                    str(event.get("contact_name") or ""),
                    str(event.get("company") or ""),
                    str(event.get("event_type") or ""),
                    str(event.get("event_status") or ""),
                    str(event.get("message") or ""),
                    str(event.get("actor") or ""),
                    json.dumps(
                        safe_json(event.get("details")),
                        default=str,
                    ),
                ]
            ).lower()
        ]

    st.markdown(
        f"**{len(filtered_events)} event(s) found**"
    )

    if filtered_events:

        audit_rows = []

        for event in filtered_events:

            audit_rows.append(
                {
                    "Event ID": event.get("id"),
                    "Date & Time": format_datetime(
                        event.get("created_at")
                    ),
                    "Lead Reference": (
                        event.get("lead_reference") or "System"
                    ),
                    "Contact": event.get("contact_name") or "—",
                    "Event Type": event.get("event_type"),
                    "Status": event.get("event_status"),
                    "Actor": event.get("actor"),
                    "Message": event.get("message"),
                }
            )

        st.dataframe(
            audit_rows,
            use_container_width=True,
            hide_index=True,
        )

        event_options = {
            (
                f"Event #{event.get('id')} | "
                f"{event.get('event_type')} | "
                f"{event.get('lead_reference') or 'System'}"
            ): event
            for event in filtered_events
        }

        st.subheader("Inspect Event Details")

        selected_event_label = st.selectbox(
            "Select an event",
            list(event_options.keys()),
        )

        selected_event = event_options[selected_event_label]

        detail_col1, detail_col2 = st.columns(2)

        with detail_col1:

            st.markdown("**Event Information**")
            st.write(f"Event ID: {selected_event.get('id')}")
            st.write(f"Event type: {selected_event.get('event_type')}")
            st.write(f"Status: {selected_event.get('event_status')}")
            st.write(f"Actor: {selected_event.get('actor')}")
            st.write(
                f"Date: {format_datetime(selected_event.get('created_at'))}"
            )

        with detail_col2:

            st.markdown("**Associated Lead**")
            st.write(
                selected_event.get("lead_reference") or "System event"
            )
            st.write(selected_event.get("contact_name") or "—")
            st.write(selected_event.get("company") or "—")

            st.markdown("**Event Message**")
            st.write(selected_event.get("message") or "No message.")

        st.divider()

        st.markdown("### Stored Event Details")

        show_event_details(selected_event)

    else:

        show_empty(
            "No events match the selected filters."
        )


st.divider()


# ============================================================
# SECTION 8 — EMAIL DRAFT ANALYTICS
# ============================================================

st.header("Email Draft Overview")

draft_col1, draft_col2, draft_col3 = st.columns(3)

draft_col1.metric("Total Drafts", len(drafts))
draft_col2.metric("Pending Review", len(pending_drafts))
draft_col3.metric("Approved", len(approved_drafts))

if drafts:

    draft_rows = []

    for draft in drafts[:15]:

        draft_rows.append(
            {
                "Draft ID": draft.get("id"),
                "Lead": draft.get("lead_reference"),
                "Contact": draft.get("contact_name"),
                "Recipient": draft.get("recipient_email"),
                "Subject": draft.get("subject"),
                "Status": draft.get("draft_status"),
                "Updated": format_datetime(draft.get("updated_at")),
            }
        )

    st.dataframe(
        draft_rows,
        use_container_width=True,
        hide_index=True,
    )

else:

    show_empty("No email drafts have been generated yet.")


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "LeadFlow AI · Dashboard & Audit Center · "
    "Data retrieved from Neon PostgreSQL"
)

st.caption(
    "AI qualification is advisory. Email drafts require human review. "
    "This dashboard does not send emails or modify lead records."
)


import json
import os
import re
from datetime import datetime

import streamlit as st
from groq import Groq

from database import (
    get_database_url,
    test_connection,
    initialize_schema,
    get_table_counts,
    find_potential_duplicates,
    create_lead,
    get_leads,
    get_lead_by_id,
    update_lead_status,
    save_qualification_result,
    update_lead_qualification,
    get_qualification_results,
    create_workflow_event,
    get_workflow_events,
    get_sales_owners,
    create_sales_owner,
    update_sales_owner_availability,
    get_owner_workloads,
    assign_lead_automatically,
    assign_lead_owner,
    unassign_lead_owner,
    save_email_draft,
    get_email_drafts,
    approve_email_draft,
    delete_email_draft,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="LeadFlow AI",
    page_icon="🎯",
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
            radial-gradient(circle at 10% 5%, rgba(91, 55, 145, 0.18), transparent 30%),
            linear-gradient(135deg, #0b1020 0%, #10172a 55%, #111827 100%);
        color: #f1f5f9;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #111827 0%, #17152d 100%);
        border-right: 1px solid rgba(148, 163, 184, 0.15);
    }

    [data-testid="stSidebar"] * {
        color: #e2e8f0;
    }

    /* Hide Streamlit's automatic multipage navigation.
       Custom sidebar navigation is used instead. */
    [data-testid="stSidebarNav"] {
        display: none !important;
    }

    h1, h2, h3 {
        color: #f8fafc;
    }

    div[data-testid="stMetric"] {
        background: rgba(30, 41, 59, 0.78);
        border: 1px solid rgba(148, 163, 184, 0.18);
        padding: 16px;
        border-radius: 14px;
    }

    div[data-testid="stMetric"] label {
        color: #cbd5e1;
    }

    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #f8fafc;
    }

    .hero {
        padding: 24px 26px;
        border-radius: 18px;
        background: linear-gradient(120deg, rgba(91, 55, 145, .35), rgba(30, 64, 175, .22));
        border: 1px solid rgba(167, 139, 250, .25);
        margin-bottom: 22px;
    }

    .muted {
        color: #aab6ca;
        font-size: 0.92rem;
    }

    .stButton > button {
        border-radius: 9px;
        border: 1px solid rgba(167, 139, 250, .35);
        font-weight: 600;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, .18);
        border-radius: 12px;
        overflow: hidden;
    }

    /* Sidebar branding */
    .sidebar-brand {
        font-size: 1.6rem;
        font-weight: 800;
        color: #ffffff;
        margin-bottom: 2px;
        line-height: 1.4;
    }

    .sidebar-subtitle {
        color: #aab6ca;
        font-size: 0.85rem;
        margin-top: 0;
        margin-bottom: 18px;
    }

    /* All four sidebar section labels use the same blue button appearance */
    .sidebar-section {
        display: flex;
        align-items: center;
        width: 100%;
        box-sizing: border-box;
        background: #29204c;
        color: #ffffff !important;
        font-size: 0.75rem;
        font-weight: 800;
        letter-spacing: 1.2px;
        line-height: 1.2;
        padding: 11px 12px;
        margin: 8px 0 8px;
        border-radius: 8px;
        text-align: left;
    }

    /* Functional navigation buttons match the APP section label */
    [data-testid="stSidebar"] .stButton {
        margin: 0 0 8px 0;
    }

    [data-testid="stSidebar"] .stButton > button {
        display: flex !important;
        align-items: center !important;
        justify-content: flex-start !important;
        width: 100%;
        min-height: 39px;
        box-sizing: border-box;
        padding: 11px 12px !important;
        margin: 0 !important;
        background: #29204c !important;
        border: 1px solid #29204c !important;
        border-radius: 8px !important;
        box-shadow: none !important;
        color: #ffffff !important;
        text-align: left !important;
        font-size: 0.75rem !important;
        font-weight: 800 !important;
        letter-spacing: 1.2px !important;
        line-height: 1.2 !important;
    }

    [data-testid="stSidebar"] .stButton > button p {
        width: 100%;
        margin: 0 !important;
        color: #ffffff !important;
        text-align: left !important;
        font-size: 0.75rem !important;
        font-weight: 800 !important;
        letter-spacing: 1.2px !important;
        line-height: 1.2 !important;
    }

    [data-testid="stSidebar"] .stButton > button:hover {
        background: #352963 !important;
        border-color: #352963 !important;
        color: #ffffff !important;
    }

    [data-testid="stSidebar"] .stButton > button:focus {
        box-shadow: 0 0 0 2px rgba(147, 197, 253, 0.45) !important;
        border-color: #93c5fd !important;
    }

    /* Keep the APP radio options close to their section label */
    [data-testid="stSidebar"] [role="radiogroup"] {
        gap: 0.15rem;
        margin-top: 0;
        margin-bottom: 8px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# SECRETS AND AI CLIENT
# ============================================================

def get_secret(name, default=None):
    try:
        value = st.secrets.get(name)
        if value:
            return value
    except Exception:
        pass

    return os.getenv(name, default)


def get_groq_client():
    api_key = get_secret("GROQ_API_KEY")

    if not api_key:
        return None

    return Groq(api_key=api_key)


def get_groq_model():
    return get_secret("GROQ_MODEL", "openai/gpt-oss-120b")


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

@st.cache_resource
def initialize_database():
    success, message = test_connection()

    if success:
        initialize_schema()

    return success, message


try:
    db_connected, db_message = initialize_database()
except Exception as exc:
    db_connected = False
    db_message = str(exc)


# ============================================================
# GENERAL HELPERS
# ============================================================

def show_page_header(title, description):
    st.title(title)
    st.markdown(
        f'<p class="muted">{description}</p>',
        unsafe_allow_html=True,
    )


def safe_dataframe(rows):
    if rows:
        st.dataframe(
            rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No records are available yet.")


def format_lead_label(lead):
    reference = lead.get("lead_reference") or f"Lead #{lead.get('id')}"
    name = lead.get("contact_name") or "Unnamed contact"
    company = lead.get("company") or "No company"
    return f"{reference} — {name} ({company})"


def get_lead_options(leads):
    return {
        format_lead_label(lead): lead["id"]
        for lead in leads
    }


def render_lead_details(lead):
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Contact**")
        st.write(lead.get("contact_name") or "Not provided")
        st.markdown("**Email**")
        st.write(lead.get("email") or "Not provided")
        st.markdown("**Company**")
        st.write(lead.get("company") or "Not provided")
        st.markdown("**Industry**")
        st.write(lead.get("industry") or "Not provided")

    with col2:
        st.markdown("**Website**")
        st.write(lead.get("website") or "Not provided")
        st.markdown("**Company size**")
        st.write(lead.get("company_size") or "Not provided")
        st.markdown("**Budget**")
        st.write(lead.get("budget") or "Not provided")
        st.markdown("**Timeline**")
        st.write(lead.get("timeline") or "Not provided")

    st.markdown("**Business need**")
    st.write(lead.get("description") or "Not provided")


# ============================================================
# AI LEAD QUALIFICATION
# ============================================================

def normalize_qualification_category(category, score=None):
    """
    Convert AI-generated category labels into exact database values.
    """
    
    original = str(category or "").strip().lower()
    normalized = re.sub(r"[\s\-]+", "_", original)
    normalized = re.sub(r"[^a-z_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    aliases = {
        "high": "high_fit",
        "high_fit": "high_fit",
        "highfit": "high_fit",
        "high_potential": "high_fit",

        "medium": "medium_fit",
        "medium_fit": "medium_fit",
        "mediumfit": "medium_fit",
        "medium_potential": "medium_fit",

        "low": "low_fit",
        "low_fit": "low_fit",
        "lowfit": "low_fit",
        "low_potential": "low_fit",

        "needs_review": "needs_review",
        "needsreview": "needs_review",
        "need_review": "needs_review",
        "review": "needs_review",
        "manual_review": "needs_review",
    }

    result = aliases.get(normalized)

    if result is None:
        if score is not None and score >= 80:
            result = "high_fit"
        elif score is not None and score >= 50:
            result = "medium_fit"
        elif score is not None:
            result = "low_fit"
        else:
            result = "needs_review"

    allowed = {
        "high_fit",
        "medium_fit",
        "low_fit",
        "needs_review",
    }

    if result not in allowed:
        result = "needs_review"

    return result


def qualify_lead(lead):
    client = get_groq_client()

    if not client:
        raise ValueError(
            "GROQ_API_KEY is missing from Streamlit secrets."
        )

    prompt = f"""
You are an experienced B2B sales qualification analyst.

Evaluate this lead using only the information supplied.
Do not invent facts.

Lead information:
Contact: {lead.get('contact_name')}
Email: {lead.get('email')}
Company: {lead.get('company')}
Industry: {lead.get('industry')}
Company size: {lead.get('company_size')}
Country: {lead.get('country')}
Website: {lead.get('website')}
Budget: {lead.get('budget')}
Timeline: {lead.get('timeline')}
Business need: {lead.get('description')}

Return valid JSON only, using this exact structure:

{{
  "score": 0,
  "category": "needs_review",
  "reasoning": "Short explanation",
  "missing_information": ["item 1", "item 2"],
  "recommended_next_action": "Specific next action",
  "human_review_required": true
}}

IMPORTANT:
The category MUST be exactly one of these four values:

- high_fit
- medium_fit
- low_fit
- needs_review

Never return High, Medium, Low, or Needs Review.
Never use spaces or capital letters in the category.

SCORING:
- 80-100: high_fit
- 50-79: medium_fit
- 0-49: low_fit

Use needs_review when essential information is insufficient
to make a reliable qualification decision.

Do not inflate the score.
Set human_review_required to true when important information
is missing or the assessment is uncertain.
"""

    response = client.chat.completions.create(
        model=get_groq_model(),
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful B2B lead qualification assistant. "
                    "Return valid JSON only. The category must be one of "
                    "high_fit, medium_fit, low_fit, needs_review."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.2,
        max_tokens=900,
    )

    content = response.choices[0].message.content or ""

    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content.strip(),
        flags=re.IGNORECASE,
    )

    content = re.sub(r"\s*```$", "", content)

    result = json.loads(content)

    score = max(
        0,
        min(100, int(result.get("score", 0))),
    )

    result["score"] = score

    original_category = result.get("category", "")

    # Normalize before returning the result to the main application.
    result["category"] = normalize_qualification_category(
        original_category,
        score,
    )

    if str(original_category).strip().lower() != result["category"]:
        result["original_ai_category"] = str(original_category)

    missing = result.get("missing_information", [])

    if not isinstance(missing, list):
        missing = [str(missing)]

    result["missing_information"] = missing

    result.setdefault(
        "reasoning",
        "No reasoning was returned.",
    )

    result.setdefault(
        "recommended_next_action",
        "Review the lead manually.",
    )

    result["human_review_required"] = bool(
        result.get("human_review_required", True)
    )

    if result["category"] == "needs_review":
        result["human_review_required"] = True

    # Final safeguard: never return an invalid database category.
    allowed_categories = {
        "high_fit",
        "medium_fit",
        "low_fit",
        "needs_review",
    }

    if result["category"] not in allowed_categories:
        raise ValueError(
            "Qualification returned an invalid database category."
        )

    return result



# ============================================================
# AI FOLLOW-UP EMAIL GENERATION
# ============================================================

def generate_followup_email(lead, email_purpose, tone, extra_instructions):
    client = get_groq_client()

    if not client:
        raise ValueError("GROQ_API_KEY is missing from Streamlit secrets.")

    qualification_rows = get_qualification_results(lead["id"])
    qualification = qualification_rows[0] if qualification_rows else None

    owner_name = lead.get("assigned_owner") or "the sales team"

    qualification_context = "No saved AI qualification result is available."

    if qualification:
        qualification_context = f"""
Latest qualification:
Score: {qualification.get('score')}
Category: {qualification.get('category')}
Reasoning: {qualification.get('reasoning')}
Recommended next action: {qualification.get('recommended_next_action')}
"""

    prompt = f"""
You are a professional B2B sales communication specialist.

Write a personalized follow-up email using the lead information below.

LEAD INFORMATION
Contact name: {lead.get('contact_name') or 'there'}
Company: {lead.get('company') or 'their organization'}
Job title: {lead.get('job_title') or 'Not provided'}
Industry: {lead.get('industry') or 'Not provided'}
Website: {lead.get('website') or 'Not provided'}
Business need: {lead.get('description') or 'Not provided'}
Budget: {lead.get('budget') or 'Not provided'}
Timeline: {lead.get('timeline') or 'Not provided'}
Assigned sales owner: {owner_name}

{qualification_context}

EMAIL PURPOSE
{email_purpose}

TONE
{tone}

ADDITIONAL INSTRUCTIONS
{extra_instructions or 'No additional instructions.'}

REQUIREMENTS
1. Write a useful, natural, professional B2B email.
2. Personalize it using the supplied information.
3. Never invent services, prices, promises, meetings, facts, or company details.
4. Do not claim that a meeting or call has already happened.
5. Do not invent a sender's name or job title.
6. Use a clear subject line.
7. Keep the email concise, usually 100-180 words.
8. Include a clear but polite next step.
9. If information is missing, do not pretend it is known.
10. Return only the subject and email body in this format:

SUBJECT: [subject line]

BODY:
[email body]
"""

    response = client.chat.completions.create(
        model=get_groq_model(),
        messages=[
            {
                "role": "system",
                "content": "You write accurate, personalized, professional B2B sales emails.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=900,
    )

    output = response.choices[0].message.content.strip()

    subject_match = re.search(
        r"SUBJECT:\s*(.*?)(?:\n|$)",
        output,
        flags=re.IGNORECASE,
    )

    body_match = re.search(
        r"BODY:\s*(.*)$",
        output,
        flags=re.IGNORECASE | re.DOTALL,
    )

    subject = subject_match.group(1).strip() if subject_match else "Follow-up"
    body = body_match.group(1).strip() if body_match else output

    return subject, body


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

with st.sidebar:

    # BRANDING — ALWAYS AT THE TOP
    st.markdown(
        """
        <div class="sidebar-brand">🎯 LeadFlow AI</div>
        <div class="sidebar-subtitle">Intelligent Lead Management</div>
        """,
        unsafe_allow_html=True,
    )

    # SECTION 1 — APP
    st.markdown(
        '<div class="sidebar-section">APP</div>',
        unsafe_allow_html=True,
    )

    page = st.radio(
        "Workspace",
        [
            "Overview",
            "Lead Intake",
            "All Leads",
            "AI Qualification",
            "Assignment & Follow-up",
            "Workflow History",
            "Database Setup",
        ],
        label_visibility="collapsed",
    )

    # SECTION 2 — AGENT WORKFLOW
    if st.button(
        "AGENT WORKFLOW",
        key="nav_agent_workflow",
        use_container_width=True,
    ):
        st.switch_page("pages/8_Agent_Workflow.py")

    # SECTION 3 — DASHBOARD & AUDIT
    if st.button(
        "DASHBOARD & AUDIT",
        key="nav_dashboard_audit",
        use_container_width=True,
    ):
        st.switch_page("pages/9_Dashboard_Audit.py")

    # SECTION 4 — HUMAN REVIEW CENTER
    if st.button(
        "HUMAN REVIEW CENTER",
        key="nav_human_review_center",
        use_container_width=True,
    ):
        st.switch_page("pages/10_Human_Review_Center.py")

    if db_connected:
        st.success("Database connected")
    else:
        st.error("Database connection failed")


if not db_connected:
    st.error(f"Unable to connect to Neon PostgreSQL: {db_message}")
    st.info(
        "Check NEON_DATABASE_URL in Streamlit Cloud secrets and verify "
        "that the database is available."
    )
    st.stop()


# ============================================================
# OVERVIEW
# ============================================================

if page == "Overview":
    show_page_header(
        "LeadFlow AI Dashboard",
        "A centralized workspace for intelligent lead intake, qualification, assignment, and follow-up.",
    )

    st.markdown(
        """
        <div class="hero">
            <h2>Turn incoming leads into meaningful opportunities.</h2>
            <p class="muted">
                Review leads, understand their potential, assign sales ownership,
                and prepare personalized follow-up communication.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    leads = get_leads()
    owners = get_owner_workloads()
    drafts = get_email_drafts()

    total_leads = len(leads)
    unassigned = sum(1 for lead in leads if not lead.get("assigned_owner_id"))
    assigned = total_leads - unassigned
    approved_drafts = sum(
        1 for draft in drafts
        if draft.get("draft_status") == "approved"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Leads", total_leads)
    c2.metric("Assigned Leads", assigned)
    c3.metric("Unassigned Leads", unassigned)
    c4.metric("Approved Email Drafts", approved_drafts)

    st.subheader("Recent Leads")

    if leads:
        recent = []
        for lead in leads[:8]:
            recent.append({
                "Reference": lead.get("lead_reference"),
                "Contact": lead.get("contact_name"),
                "Company": lead.get("company"),
                "Status": lead.get("status"),
                "Priority": lead.get("priority"),
                "Owner": lead.get("assigned_owner") or "Unassigned",
            })

        st.dataframe(recent, use_container_width=True, hide_index=True)
    else:
        st.info("No leads have been added yet.")

    st.subheader("Sales Team Overview")

    if owners:
        st.dataframe(
            [
                {
                    "Sales Owner": owner["full_name"],
                    "Specialization": owner["specialization"],
                    "Available": "Yes" if owner["is_available"] else "No",
                    "Active Leads": owner["active_leads"],
                    "Capacity": owner["active_lead_limit"],
                }
                for owner in owners
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Add sales owners in Assignment & Follow-up.")


# ============================================================
# LEAD INTAKE
# ============================================================

elif page == "Lead Intake":
    show_page_header(
        "Lead Intake",
        "Register a new prospect and check for possible duplicate records.",
    )

    with st.form("lead_intake_form"):
        col1, col2 = st.columns(2)

        with col1:
            contact_name = st.text_input("Contact name *")
            email = st.text_input("Email address *")
            company = st.text_input("Company")
            job_title = st.text_input("Job title")
            website = st.text_input("Company website")
            industry = st.text_input("Industry")

        with col2:
            company_size = st.selectbox(
                "Company size",
                ["Not specified", "1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"],
            )
            country = st.text_input("Country")
            source = st.selectbox(
                "Lead source",
                ["website_form", "LinkedIn", "Referral", "Email", "Event", "Other"],
            )
            budget = st.selectbox(
                "Budget range",
                [
                    "Not specified",
                    "Under $1,000",
                    "$1,000-$5,000",
                    "$5,000-$10,000",
                    "$10,000-$25,000",
                    "$25,000+",
                    "Custom",
                ],
            )

            budget_custom = st.text_input(
                "Custom budget (optional)",
                placeholder="Enter a budget range if you selected Custom",
                help="This value is used only when Budget range is set to Custom.",
            )
            timeline = st.selectbox(
                "Expected timeline",
                [
                    "Not specified",
                    "Immediately",
                    "Within 1 month",
                    "1-3 months",
                    "3-6 months",
                    "More than 6 months",
                    "Custom",
                ],
            )

            timeline_custom = st.text_input(
                "Custom expected timeline (optional)",
                placeholder="Enter a timeline if you selected Custom",
                help="This value is used only when Expected timeline is set to Custom.",
            )

        description = st.text_area(
            "Describe the prospect's requirement",
            placeholder="What problem are they trying to solve? What service or solution are they interested in?",
        )

        consent = st.checkbox("The prospect has consented to be contacted.")

        submitted = st.form_submit_button(
            "Check and Save Lead",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        if not contact_name.strip() or not email.strip():
            st.error("Contact name and email address are required.")
        elif "@" not in email or "." not in email.split("@")[-1]:
            st.error("Please enter a valid email address.")
        elif budget == "Custom" and not budget_custom.strip():
            st.error("Please enter a custom budget range.")
        elif timeline == "Custom" and not timeline_custom.strip():
            st.error("Please enter a custom expected timeline.")
        else:
            budget_value = (
                budget_custom.strip()
                if budget == "Custom"
                else None
                if budget == "Not specified"
                else budget
            )

            timeline_value = (
                timeline_custom.strip()
                if timeline == "Custom"
                else None
                if timeline == "Not specified"
                else timeline
            )

            lead_data = {
                "contact_name": contact_name,
                "email": email,
                "company": company,
                "job_title": job_title,
                "website": website,
                "industry": industry,
                "company_size": None if company_size == "Not specified" else company_size,
                "country": country,
                "source": source,
                "budget": budget_value,
                "timeline": timeline_value,
                "description": description,
                "consent_to_contact": consent,
            }

            try:
                matches = find_potential_duplicates(lead_data)

                if matches:
                    st.warning(
                        "Potential matches found. Review them below, then confirm "
                        "if this is a separate lead."
                    )
                    st.dataframe(matches, use_container_width=True, hide_index=True)

                    if st.button("Confirm and Save as a Separate Lead"):
                        created = create_lead(lead_data)
                        create_workflow_event(
                            created["id"],
                            "lead_created",
                            "New lead created after duplicate review.",
                            details={"duplicate_reviewed": True},
                        )
                        st.success(
                            f"Lead {created['lead_reference']} was saved successfully."
                        )
                        st.rerun()

                else:
                    created = create_lead(lead_data)
                    create_workflow_event(
                        created["id"],
                        "lead_created",
                        "New lead created through Lead Intake.",
                    )
                    st.success(
                        f"Lead {created['lead_reference']} was saved successfully."
                    )
                    st.rerun()

            except Exception as exc:
                st.error(f"Lead check/save failed: {exc}")


# ============================================================
# ALL LEADS
# ============================================================

elif page == "All Leads":
    show_page_header(
        "All Leads",
        "Search, review, and update your lead records.",
    )

    search = st.text_input(
        "Search leads",
        placeholder="Search by contact, email, company, or lead reference...",
    )

    leads = get_leads(search)

    if leads:
        status_options = sorted({
            str(lead.get("status") or "new")
            for lead in leads
        })

        selected_status = st.selectbox(
            "Filter by status",
            ["All statuses"] + status_options,
        )

        filtered = leads

        if selected_status != "All statuses":
            filtered = [
                lead for lead in leads
                if (lead.get("status") or "new") == selected_status
            ]

        st.dataframe(
            [
                {
                    "Reference": lead.get("lead_reference"),
                    "Contact": lead.get("contact_name"),
                    "Email": lead.get("email"),
                    "Company": lead.get("company"),
                    "Status": lead.get("status"),
                    "Priority": lead.get("priority"),
                    "Owner": lead.get("assigned_owner") or "Unassigned",
                    "Created": lead.get("created_at"),
                }
                for lead in filtered
            ],
            use_container_width=True,
            hide_index=True,
        )

        options = get_lead_options(filtered)

        if options:
            selected_label = st.selectbox(
                "Select a lead to view or update",
                list(options.keys()),
                key="all_leads_selected",
            )

            selected_lead = get_lead_by_id(options[selected_label])

            if selected_lead:
                with st.expander("Lead details", expanded=True):
                    render_lead_details(selected_lead)

                status_values = [
                    "new",
                    "contacted",
                    "qualified",
                    "in progress",
                    "closed",
                    "won",
                    "lost",
                    "disqualified",
                ]

                current_status = selected_lead.get("status") or "new"

                if current_status not in status_values:
                    status_values.append(current_status)

                new_status = st.selectbox(
                    "Update lead status",
                    status_values,
                    index=status_values.index(current_status),
                )

                if st.button("Save Status", type="primary"):
                    update_lead_status(selected_lead["id"], new_status)
                    create_workflow_event(
                        selected_lead["id"],
                        "lead_status_updated",
                        f"Lead status changed to {new_status}.",
                    )
                    st.success("Lead status updated.")
                    st.rerun()

    else:
        st.info("No leads match your search.")


# ============================================================
# AI QUALIFICATION
# ============================================================

elif page == "AI Qualification":
    show_page_header(
        "AI Lead Qualification",
        "Use Groq AI to assess lead potential and recommend the next action.",
    )

    leads = get_leads()

    if not leads:
        st.info("Add a lead before running AI qualification.")
    else:
        options = get_lead_options(leads)

        selected_label = st.selectbox(
            "Select a lead",
            list(options.keys()),
        )

        lead_id = options[selected_label]
        lead = get_lead_by_id(lead_id)

        if lead:
            with st.expander("Lead information", expanded=True):
                render_lead_details(lead)

            if st.button("Run AI Qualification", type="primary"):
                try:
                    with st.spinner("Analyzing lead information..."):
                        result = qualify_lead(lead)

                        save_qualification_result(
                            lead_id,
                            result,
                            model_name=get_groq_model(),
                        )

                        update_lead_qualification(
                            lead_id,
                            result["score"],
                            result["category"],
                        )

                        create_workflow_event(
                            lead_id,
                            "ai_qualification_completed",
                            "AI lead qualification completed.",
                            details=result,
                        )

                    st.session_state["latest_qualification"] = {
                        "lead_id": lead_id,
                        "result": result,
                    }

                    st.success("Lead qualification completed.")

                except Exception as exc:
                    st.error(f"Unable to qualify this lead: {exc}")

            latest = st.session_state.get("latest_qualification")

            if latest and latest["lead_id"] == lead_id:
                result = latest["result"]

                st.subheader("Qualification Result")

                c1, c2, c3 = st.columns(3)
                c1.metric("Lead Score", f"{result['score']}/100")
                c2.metric("Category", result["category"])
                c3.metric(
                    "Human Review",
                    "Required" if result.get("human_review_required") else "Not required",
                )

                st.markdown("**Reasoning**")
                st.write(result.get("reasoning"))

                st.markdown("**Missing Information**")
                missing = result.get("missing_information", [])

                if missing:
                    for item in missing:
                        st.write(f"• {item}")
                else:
                    st.write("No missing information identified.")

                st.markdown("**Recommended Next Action**")
                st.info(result.get("recommended_next_action"))

            history = get_qualification_results(lead_id)

            if history:
                st.subheader("Saved Qualification History")
                safe_dataframe([
                    {
                        "Score": item.get("score"),
                        "Category": item.get("category"),
                        "Model": item.get("model_name"),
                        "Created": item.get("created_at"),
                    }
                    for item in history
                ])


# ============================================================
# ASSIGNMENT & FOLLOW-UP
# ============================================================

elif page == "Assignment & Follow-up":
    show_page_header(
        "Assignment & Follow-up",
        "Manage sales ownership and prepare personalized follow-up emails.",
    )

    # --------------------------------------------------------
    # SALES OWNER MANAGEMENT
    # --------------------------------------------------------

    st.header("Sales Team")

    with st.expander("Add a Sales Owner"):
        with st.form("add_sales_owner_form"):
            owner_name = st.text_input("Full name")
            owner_email = st.text_input("Email address")
            specialization = st.text_input(
                "Specialization",
                placeholder="For example: Healthcare, Biotechnology, SaaS",
            )
            capacity = st.number_input(
                "Maximum active leads",
                min_value=1,
                max_value=500,
                value=20,
            )

            add_owner = st.form_submit_button(
                "Add Sales Owner",
                type="primary",
            )

        if add_owner:
            if not owner_name.strip() or not owner_email.strip():
                st.error("Name and email are required.")
            elif "@" not in owner_email:
                st.error("Enter a valid email address.")
            else:
                try:
                    create_sales_owner(
                        owner_name,
                        owner_email,
                        specialization or "General",
                        capacity,
                    )
                    st.success("Sales owner added.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Unable to add sales owner: {exc}")

    owners = get_owner_workloads()

    if owners:
        st.dataframe(
            [
                {
                    "Name": owner["full_name"],
                    "Email": owner["email"],
                    "Specialization": owner["specialization"],
                    "Available": "Yes" if owner["is_available"] else "No",
                    "Active Leads": owner["active_leads"],
                    "Capacity": owner["active_lead_limit"],
                }
                for owner in owners
            ],
            use_container_width=True,
            hide_index=True,
        )

        owner_map = {
            f"{owner['full_name']} — {owner['specialization']}": owner
            for owner in owners
        }

        selected_owner_label = st.selectbox(
            "Manage owner availability",
            list(owner_map.keys()),
        )
        selected_owner = owner_map[selected_owner_label]

        new_availability = st.toggle(
            "Owner is available for new assignments",
            value=bool(selected_owner["is_available"]),
            key=f"owner_available_{selected_owner['id']}",
        )

        if new_availability != bool(selected_owner["is_available"]):
            update_sales_owner_availability(
                selected_owner["id"],
                new_availability,
            )
            st.success("Owner availability updated.")
            st.rerun()

    else:
        st.info("No sales owners have been added yet.")

    # --------------------------------------------------------
    # AUTOMATIC ASSIGNMENT
    # --------------------------------------------------------

    st.divider()
    st.header("Automatic Assignment")

    leads = get_leads()
    unassigned_leads = [
        lead for lead in leads
        if not lead.get("assigned_owner_id")
    ]

    st.metric("Unassigned Leads", len(unassigned_leads))

    if owners and unassigned_leads:
        if st.button("Automatically Assign All Eligible Leads"):
            assigned_count = 0
            not_assigned = []

            with st.spinner(
                "Assigning leads based on specialization and workload..."
            ):
                for lead in unassigned_leads:
                    success, message, selected = assign_lead_automatically(
                        lead["id"]
                    )

                    if success:
                        assigned_count += 1
                    else:
                        not_assigned.append({
                            "reference": lead.get("lead_reference", "Unknown"),
                            "contact": lead.get("contact_name", "Unknown"),
                            "company": lead.get("company", "Not provided"),
                            "industry": lead.get("industry", "Not specified"),
                            "reason": message or "No assignment reason provided."
                        })

            st.session_state["assignment_run_result"] = {
                "assigned_count": assigned_count,
                "not_assigned": not_assigned
            }

            st.rerun()

    elif not owners:
        st.warning(
            "No sales owners have been added. "
            "Automatic assignment cannot proceed."
        )
        st.write(
            "**Reason:** There are no sales owners available in the system."
        )

    elif not unassigned_leads:
        st.info("There are no unassigned leads.")

    # Display assignment results after the page refreshes.
    assignment_result = st.session_state.get("assignment_run_result")

    if assignment_result:
        assigned_count = assignment_result["assigned_count"]
        not_assigned = assignment_result["not_assigned"]

        if assigned_count > 0:
            st.success(
                f"{assigned_count} lead(s) assigned successfully."
            )

        if not_assigned:
            if assigned_count == 0:
                st.error(
                    "No leads could be assigned to a sales owner."
                )
            else:
                st.warning(
                    f"{len(not_assigned)} lead(s) could not be assigned."
                )

            st.markdown("### Unassigned Leads — Reasons")

            for item in not_assigned:
                with st.expander(
                    f"{item['reference']} — {item['company']}"
                ):
                    st.write(f"**Contact:** {item['contact']}")
                    st.write(f"**Industry:** {item['industry']}")
                    st.write(f"**Reason:** {item['reason']}")

            st.info(
                "Review the reasons above. You may need to add a suitable "
                "sales owner, update an owner's specialization, make an "
                "owner available, or increase their capacity. You can also "
                "use Manual Assignment."
            )

    # --------------------------------------------------------
    # MANUAL ASSIGNMENT
    # --------------------------------------------------------

    st.divider()
    st.header("Manual Assignment")

    available_owners = [
        owner for owner in owners
        if owner["is_available"]
        and int(owner["active_leads"]) < int(owner["active_lead_limit"])
    ]

    if unassigned_leads and available_owners:
        lead_map = get_lead_options(unassigned_leads)
        selected_lead_label = st.selectbox(
            "Select an unassigned lead",
            list(lead_map.keys()),
            key="manual_assignment_lead",
        )

        owner_map = {
            f"{owner['full_name']} — {owner['active_leads']}/{owner['active_lead_limit']} active leads":
                owner["id"]
            for owner in available_owners
        }

        selected_owner_assignment = st.selectbox(
            "Select a sales owner",
            list(owner_map.keys()),
            key="manual_assignment_owner",
        )

        if st.button("Assign Lead Manually"):
            success, message = assign_lead_owner(
                lead_map[selected_lead_label],
                owner_map[selected_owner_assignment],
            )

            if success:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

    elif unassigned_leads:
        st.warning(
            "No available sales owner has remaining capacity. "
            "The leads will stay in the unassigned queue."
        )
    else:
        st.info("No unassigned leads are waiting for manual assignment.")

    # --------------------------------------------------------
    # CURRENT ASSIGNMENTS / UNASSIGN
    # --------------------------------------------------------

    st.divider()
    st.header("Current Assignments")

    assigned_leads = [
        lead for lead in leads
        if lead.get("assigned_owner_id")
    ]

    if assigned_leads:
        st.dataframe(
            [
                {
                    "Reference": lead.get("lead_reference"),
                    "Contact": lead.get("contact_name"),
                    "Company": lead.get("company"),
                    "Assigned Owner": lead.get("assigned_owner"),
                    "Status": lead.get("status"),
                }
                for lead in assigned_leads
            ],
            use_container_width=True,
            hide_index=True,
        )

        assigned_map = get_lead_options(assigned_leads)
        selected_assigned_label = st.selectbox(
            "Select an assigned lead to unassign",
            list(assigned_map.keys()),
        )

        if st.button("Remove Sales Owner Assignment"):
            unassign_lead_owner(assigned_map[selected_assigned_label])
            st.success("Sales owner assignment removed.")
            st.rerun()

    else:
        st.info("No leads have been assigned yet.")

    # ========================================================
    # AI EMAIL DRAFTING
    # ========================================================

    st.divider()
    st.header("AI Follow-up Email Generator")

    st.markdown(
        """
        Generate a personalized email using the lead's saved information.
        Review and edit the result before saving it to your database.
        """
    )

    if not leads:
        st.info("Add a lead before generating a follow-up email.")
    else:
        email_lead_options = get_lead_options(leads)

        email_lead_label = st.selectbox(
            "Choose a lead for follow-up",
            list(email_lead_options.keys()),
            key="email_lead_selector",
        )

        email_lead_id = email_lead_options[email_lead_label]
        email_lead = get_lead_by_id(email_lead_id)

        if email_lead:
            with st.expander("Selected lead information"):
                render_lead_details(email_lead)

            if not email_lead.get("consent_to_contact"):
                st.warning(
                    "This lead does not currently have recorded consent to be contacted. "
                    "You can prepare a draft for review, but verify permission and "
                    "applicable requirements before any outreach."
                )

            purpose = st.selectbox(
                "Email purpose",
                [
                    "Initial follow-up after receiving an inquiry",
                    "Follow-up after sharing information",
                    "Request missing project information",
                    "Schedule an introductory discussion",
                    "Follow-up after no response",
                    "Check project timeline and readiness",
                    "Custom follow-up",
                ],
            )

            tone = st.selectbox(
                "Email tone",
                [
                    "Professional and friendly",
                    "Formal and concise",
                    "Warm and consultative",
                    "Confident and persuasive",
                ],
            )

            extra_instructions = st.text_area(
                "Additional instructions (optional)",
                placeholder=(
                    "For example: Mention our bioinformatics services, "
                    "ask about the expected project timeline, or keep the "
                    "email especially concise."
                ),
            )

            if st.button(
                "Generate AI Email Draft",
                type="primary",
                use_container_width=True,
            ):
                try:
                    with st.spinner("Generating a personalized email with Groq AI..."):
                        subject, body = generate_followup_email(
                            email_lead,
                            purpose,
                            tone,
                            extra_instructions,
                        )

                    st.session_state["generated_email"] = {
                        "lead_id": email_lead_id,
                        "recipient": email_lead.get("email") or "",
                        "subject": subject,
                        "body": body,
                    }

                    st.success("Email draft generated. Review it below.")

                except Exception as exc:
                    st.error(f"Unable to generate email: {exc}")

            generated = st.session_state.get("generated_email")

            if generated and generated["lead_id"] == email_lead_id:
                st.subheader("Review and Edit Generated Email")

                recipient = st.text_input(
                    "Recipient email",
                    value=generated["recipient"],
                    key=f"generated_recipient_{email_lead_id}",
                )

                subject = st.text_input(
                    "Email subject",
                    value=generated["subject"],
                    key=f"generated_subject_{email_lead_id}",
                )

                body = st.text_area(
                    "Email body",
                    value=generated["body"],
                    height=300,
                    key=f"generated_body_{email_lead_id}",
                )

                if st.button(
                    "Save Email Draft",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        if not recipient.strip() or "@" not in recipient:
                            st.error("Enter a valid recipient email address.")
                        elif not subject.strip() or not body.strip():
                            st.error("Subject and email body cannot be empty.")
                        else:
                            draft_id = save_email_draft(
                                email_lead_id,
                                recipient,
                                subject,
                                body,
                            )

                            st.success(
                                f"Email draft saved successfully. Draft ID: {draft_id}"
                            )
                            st.rerun()

                    except Exception as exc:
                        st.error(f"Unable to save email draft: {exc}")

    # --------------------------------------------------------
    # SAVED EMAIL DRAFTS
    # --------------------------------------------------------

    st.divider()
    st.header("Saved Email Drafts")

    saved_drafts = get_email_drafts()

    if saved_drafts:
        st.dataframe(
            [
                {
                    "Draft ID": draft["id"],
                    "Lead": draft.get("lead_reference"),
                    "Contact": draft.get("contact_name"),
                    "Recipient": draft.get("recipient_email"),
                    "Subject": draft.get("subject"),
                    "Status": draft.get("draft_status"),
                    "Updated": draft.get("updated_at"),
                }
                for draft in saved_drafts
            ],
            use_container_width=True,
            hide_index=True,
        )

        draft_options = {
            (
                f"Draft #{draft['id']} — "
                f"{draft.get('contact_name') or 'Unknown contact'} — "
                f"{draft.get('subject')}"
            ): draft
            for draft in saved_drafts
        }

        selected_draft_label = st.selectbox(
            "Select a saved draft",
            list(draft_options.keys()),
        )

        selected_draft = draft_options[selected_draft_label]

        with st.expander("View or edit selected draft", expanded=True):
            edit_recipient = st.text_input(
                "Recipient",
                value=selected_draft.get("recipient_email") or "",
                key=f"edit_recipient_{selected_draft['id']}",
            )

            edit_subject = st.text_input(
                "Subject",
                value=selected_draft.get("subject") or "",
                key=f"edit_subject_{selected_draft['id']}",
            )

            edit_body = st.text_area(
                "Email body",
                value=selected_draft.get("body") or "",
                height=260,
                key=f"edit_body_{selected_draft['id']}",
            )

            st.caption(
                f"Current status: {selected_draft.get('draft_status')}"
            )

            col_save, col_approve, col_delete = st.columns(3)

            with col_save:
                if st.button(
                    "Save Changes",
                    key=f"save_draft_{selected_draft['id']}",
                    use_container_width=True,
                ):
                    try:
                        save_email_draft(
                            selected_draft["lead_id"],
                            edit_recipient,
                            edit_subject,
                            edit_body,
                            draft_id=selected_draft["id"],
                        )
                        st.success("Draft changes saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Unable to update draft: {exc}")

            with col_approve:
                if st.button(
                    "Approve Draft",
                    key=f"approve_draft_{selected_draft['id']}",
                    use_container_width=True,
                    disabled=selected_draft.get("draft_status") == "approved",
                ):
                    success, message = approve_email_draft(
                        selected_draft["id"],
                        approved_by="Administrator",
                    )

                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

            with col_delete:
                if st.button(
                    "Delete Draft",
                    key=f"delete_draft_{selected_draft['id']}",
                    use_container_width=True,
                ):
                    if delete_email_draft(selected_draft["id"]):
                        st.success("Draft deleted.")
                        st.rerun()
                    else:
                        st.error("Draft could not be found.")

            if selected_draft.get("draft_status") == "approved":
                st.success(
                    "This draft is approved. Approval does not send an email."
                )

    else:
        st.info("No email drafts have been saved yet.")

    st.caption(
        "Email sending is intentionally not enabled. "
        "Generated emails remain drafts until reviewed and approved."
    )


# ============================================================
# WORKFLOW HISTORY
# ============================================================

elif page == "Workflow History":
    show_page_header(
        "Workflow History",
        "Review the activity and audit trail recorded by LeadFlow AI.",
    )

    events = get_workflow_events()

    if events:
        st.dataframe(
            [
                {
                    "Date": event.get("created_at"),
                    "Lead Reference": event.get("lead_reference") or "System",
                    "Contact": event.get("contact_name") or "—",
                    "Event": event.get("event_type"),
                    "Status": event.get("event_status"),
                    "Message": event.get("message"),
                    "Actor": event.get("actor"),
                }
                for event in events
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No workflow events have been recorded yet.")


# ============================================================
# DATABASE SETUP
# ============================================================

elif page == "Database Setup":
    show_page_header(
        "Database Setup",
        "Check the Neon PostgreSQL connection and review stored record counts.",
    )

    if db_connected:
        st.success("Successfully connected to Neon PostgreSQL.")
        st.code(str(db_message))

        try:
            counts = get_table_counts()

            st.subheader("Database Record Counts")

            columns = st.columns(len(counts))

            for index, (table, count) in enumerate(counts.items()):
                with columns[index]:
                    st.metric(
                        table.replace("_", " ").title(),
                        count,
                    )

        except Exception as exc:
            st.error(f"Unable to retrieve table counts: {exc}")

    else:
        st.error(f"Database connection failed: {db_message}")

    st.subheader("Configuration Checklist")

    st.markdown(
        """
        - `NEON_DATABASE_URL` must be configured in Streamlit Cloud secrets.
        - `GROQ_API_KEY` is required for AI qualification and email generation.
        - `GROQ_MODEL` is optional; the app has a default model.
        - Existing Neon tables are used; this application does not recreate them.
        """
    )

    if st.button("Refresh Database Connection"):
        st.cache_resource.clear()
        st.rerun()

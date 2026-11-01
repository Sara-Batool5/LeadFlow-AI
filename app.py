import re
from datetime import datetime
import pandas as pd
import streamlit as st
from database import (
    get_database_url, test_connection, initialize_schema, get_table_counts,
    DatabaseConfigurationError, create_lead, get_leads, get_recent_events,
    get_lead_by_email
)

st.set_page_config(page_title="LeadFlow AI", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { color-scheme: dark; }
.stApp { background: linear-gradient(135deg,#0b1020 0%,#14152d 55%,#21143a 100%); color:#f4f2ff; }
[data-testid="stHeader"] { background:rgba(11,16,32,.96); border-bottom:1px solid rgba(167,139,250,.18); }
[data-testid="stSidebar"] { background:#101326; border-right:1px solid rgba(167,139,250,.22); }
[data-testid="stSidebar"] * { color:#e9e7ff; }
.stApp p,.stApp label,.stApp li,.stApp [data-testid="stMarkdownContainer"] { color:#e9e7ff; }
h1,h2,h3,h4 { color:#fff !important; }
.hero { padding:1.4rem 1.6rem; border:1px solid rgba(167,139,250,.35); border-radius:18px; background:linear-gradient(120deg,rgba(124,58,237,.22),rgba(59,130,246,.10)); margin-bottom:1.2rem; }
.hero h1 { margin-bottom:.35rem; color:#fff !important; }
.hero p { color:#d8d5f0 !important; margin-bottom:0; }
.small-note { color:#aaa7c8 !important; font-size:.84rem; }
div[data-testid="stMetric"] { background:rgba(23,27,53,.82); border:1px solid rgba(167,139,250,.3); padding:1rem; border-radius:14px; }
div[data-testid="stMetricLabel"] { color:#c5c1e4 !important; }
div[data-testid="stMetricValue"] { color:#fff !important; }
.stApp input,.stApp textarea,.stApp [data-baseweb="select"] > div { background-color:#171b35 !important; color:#f4f2ff !important; border-color:#62558f !important; border-radius:10px !important; }
.stApp input::placeholder,.stApp textarea::placeholder { color:#aaa5c9 !important; opacity:1 !important; }
.stApp button[kind="primary"],.stApp [data-testid="stFormSubmitButton"] button { background:linear-gradient(90deg,#7c3aed,#5b5bd6) !important; color:#fff !important; border:1px solid #8b5cf6 !important; border-radius:10px !important; }
.stApp [data-testid="stDataFrame"],.stApp [data-testid="stTable"] { border:1px solid #514875; border-radius:12px; overflow:hidden; }
.stApp hr { border-color:rgba(167,139,250,.22); }
</style>
""", unsafe_allow_html=True)

def show_db_error(exc):
    if isinstance(exc, DatabaseConfigurationError):
        st.error(str(exc))
    else:
        st.error("The database operation failed. Check Database Setup and your Neon connection. Sensitive connection details are hidden.")

with st.sidebar:
    st.markdown("## 🎯 LeadFlow AI")
    st.caption("Intelligent lead workflow")
    st.divider()
    page = st.radio("Navigation", ["Overview", "Lead Intake", "All Leads", "AI Qualification", "Assignment & Follow-up", "Workflow History", "Database Setup"], index=0)
    st.divider()
    st.caption("Phase 3 · Functional lead intake")
    st.caption("Demo environment · Use synthetic/test data")

st.markdown("""<div class="hero"><h1>LeadFlow AI</h1><p>From form submission to qualified lead, assigned owner, and reviewed follow-up draft.</p></div>""", unsafe_allow_html=True)

if page == "Database Setup":
    st.subheader("Neon PostgreSQL connection")
    st.write("Configure your Neon connection string in Streamlit Community Cloud Secrets, then test the connection and verify the LeadFlow AI tables.")
    st.warning("Never paste your database connection string into this page, chat, or GitHub. Add it only in Streamlit's Secrets settings.")
    st.write("**Connection string configured:** " + ("Yes" if get_database_url() else "No"))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Test database connection", type="primary", use_container_width=True):
            try:
                st.success(test_connection())
            except Exception as exc:
                show_db_error(exc)
    with c2:
        if st.button("Create / verify tables", use_container_width=True):
            try:
                initialize_schema()
                st.success("Database schema is ready. Required tables were created or already existed.")
            except Exception as exc:
                show_db_error(exc)

    st.markdown("### Tables in this phase")
    tables_df = pd.DataFrame([
        {"Table": "leads", "Purpose": "Submitted lead/contact details and workflow status"},
        {"Table": "sales_owners", "Purpose": "Sales owner names, email, specialization, and availability"},
        {"Table": "qualification_results", "Purpose": "AI qualification scores, categories, and explanations (later phase)"},
        {"Table": "email_drafts", "Purpose": "Follow-up drafts and review status (later phase)"},
        {"Table": "workflow_events", "Purpose": "Chronological audit trail of workflow events"},
    ])
    st.dataframe(tables_df, use_container_width=True, hide_index=True, height=225)

    st.markdown("### Table record counts")
    if st.button("Refresh database counts", type="primary"):
        try:
            st.session_state["db_counts"] = get_table_counts()
        except Exception as exc:
            show_db_error(exc)
    if "db_counts" not in st.session_state:
        try:
            st.session_state["db_counts"] = get_table_counts()
        except Exception:
            st.session_state["db_counts"] = None
    counts = st.session_state.get("db_counts")
    if counts:
        counts_df = pd.DataFrame([{"Table": name, "Records": int(count)} for name, count in counts.items()])
        total = int(sum(counts.values()))
        st.dataframe(counts_df, use_container_width=True, hide_index=True, height=235)
        st.metric("Total records across these tables", total)
        st.caption("Zero records is normal before you submit leads or add sales owners.")
    else:
        st.info("Connect to Neon and click “Refresh database counts” to load the record counts.")

elif page == "Overview":
    st.subheader("Sales pipeline overview")
    try:
        leads = get_leads()
        total = len(leads)
        new_count = sum(1 for lead in leads if lead.get("status") == "new")
        qualified_count = sum(1 for lead in leads if lead.get("status") == "qualified")
        needs_review_count = sum(1 for lead in leads if lead.get("status") == "needs_review")
        cols = st.columns(4)
        for col, (label, value) in zip(cols, [("Total leads", total), ("New", new_count), ("Qualified", qualified_count), ("Needs review", needs_review_count)]):
            col.metric(label, value)
        st.caption(f"Live database data · Refreshed {datetime.now().strftime('%d %b %Y, %H:%M')}")
        st.subheader("Recent leads")
        if leads:
            st.dataframe(pd.DataFrame(leads).head(8), use_container_width=True, hide_index=True)
        else:
            st.info("No leads yet. Open Lead Intake to add your first test lead.")
    except Exception as exc:
        show_db_error(exc)

elif page == "Lead Intake":
    st.subheader("Submit a new lead")
    st.write("Add a prospect to the database. LeadFlow checks the email address for duplicates before saving.")
    with st.form("lead_intake_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            full_name = st.text_input("Full name *", placeholder="e.g., Ahmed Khan")
            email = st.text_input("Work email *", placeholder="name@company.com")
            company = st.text_input("Company", placeholder="Company name")
            job_title = st.text_input("Job title", placeholder="e.g., Research Director")
            website = st.text_input("Company website", placeholder="https://example.com")
            country = st.text_input("Country", placeholder="e.g., Pakistan")
        with c2:
            industry = st.selectbox("Industry", ["Not specified", "Biotechnology", "Healthcare", "Pharmaceuticals", "Education / Research", "Technology / Software", "Manufacturing", "Other"])
            company_size = st.selectbox("Company size", ["Not specified", "1–10", "11–50", "51–200", "201–500", "501–1,000", "1,001+"])
            budget_range = st.selectbox("Budget range", ["Not specified", "Not disclosed", "Under $1,000", "$1,000–$5,000", "$5,000–$20,000", "$20,000+"])
            timeline = st.selectbox("Expected timeline", ["Not specified", "Immediately", "Within 1 month", "Within 3 months", "3+ months", "Exploring"])
            source = st.selectbox("Lead source", ["website_form", "referral", "LinkedIn", "email_campaign", "event", "other"])
            consent = st.checkbox("The prospect has consented to be contacted.")
        need_description = st.text_area("What does the prospect need? *", placeholder="Describe their challenge, goals, or service requirements.", height=130)
        submitted = st.form_submit_button("Check for duplicates & save lead", type="primary", use_container_width=True)

    if submitted:
        errors = []
        if len(full_name.strip()) < 2:
            errors.append("Enter the prospect's full name.")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()):
            errors.append("Enter a valid email address.")
        if len(need_description.strip()) < 10:
            errors.append("Describe the prospect's need in at least 10 characters.")
        if website.strip() and not re.match(r"^https?://", website.strip(), re.I):
            errors.append("Company website must start with http:// or https://.")
        if errors:
            for error in errors:
                st.error(error)
        else:
            try:
                existing = get_lead_by_email(email.strip())
                if existing:
                    st.warning(f"Possible duplicate: {existing['lead_reference']} already uses this email ({existing['full_name']}). No new record was created.")
                    st.dataframe(pd.DataFrame([existing]), use_container_width=True, hide_index=True)
                else:
                    record = create_lead({
                        "full_name": full_name.strip(),
                        "email": email.strip().lower(),
                        "company": company.strip() or None,
                        "job_title": job_title.strip() or None,
                        "website": website.strip() or None,
                        "company_size": None if company_size == "Not specified" else company_size,
                        "industry": None if industry == "Not specified" else industry,
                        "country": country.strip() or None,
                        "source": source,
                        "need_description": need_description.strip(),
                        "budget_range": None if budget_range == "Not specified" else budget_range,
                        "timeline": None if timeline == "Not specified" else timeline,
                        "consent_to_contact": consent,
                    })
                    st.success(f"Lead saved successfully! Reference: {record['lead_reference']}")
                    st.info("Phase 3 stores and lists leads. AI qualification, owner assignment, and follow-up drafting are planned for later phases.")
            except Exception as exc:
                show_db_error(exc)

elif page == "All Leads":
    st.subheader("All leads")
    try:
        leads = get_leads()
        if not leads:
            st.info("No saved leads yet. Submit one from the Lead Intake page.")
        else:
            search = st.text_input("Search leads", placeholder="Search by name, email, company, or reference")
            statuses = ["All statuses"] + sorted({lead.get("status", "new") for lead in leads})
            status_filter = st.selectbox("Filter by status", statuses)
            filtered = leads
            if search.strip():
                needle = search.strip().lower()
                filtered = [lead for lead in filtered if any(needle in str(lead.get(key) or "").lower() for key in ["lead_reference", "full_name", "email", "company", "industry"])]
            if status_filter != "All statuses":
                filtered = [lead for lead in filtered if lead.get("status") == status_filter]
            st.caption(f"Showing {len(filtered)} of {len(leads)} saved leads")
            display_columns = ["lead_reference", "full_name", "email", "company", "industry", "status", "priority", "created_at"]
            st.dataframe(pd.DataFrame([{key: lead.get(key) for key in display_columns} for lead in filtered]), use_container_width=True, hide_index=True)
    except Exception as exc:
        show_db_error(exc)

elif page == "AI Qualification":
    st.subheader("AI qualification")
    st.write("Qualification scores, categories, explanations, and recommended next actions will be added in Phase 5.")
    st.info("Groq integration is not active in this phase.")

elif page == "Assignment & Follow-up":
    st.subheader("Assignment & follow-up")
    left, right = st.columns(2)
    with left:
        st.markdown("### Sales owner assignment")
        st.write("Owner routing rules and workload-aware assignment will be added in Phase 6.")
    with right:
        st.markdown("### Email draft review")
        st.write("AI-generated drafts and human review controls will be added in Phase 7.")
    st.info("No emails are sent by this application.")

elif page == "Workflow History":
    st.subheader("Workflow history")
    try:
        events = get_recent_events()
        if events:
            st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
        else:
            st.info("No workflow events recorded yet. New lead submissions will appear here.")
    except Exception as exc:
        show_db_error(exc)

st.divider()
st.markdown('<p class="small-note">LeadFlow AI · Phase 3 · Functional lead intake, duplicate-email check, persistent lead list, and workflow event logging. AI and assignment integrations are not active yet.</p>', unsafe_allow_html=True)

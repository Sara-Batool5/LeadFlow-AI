import streamlit as st
from datetime import datetime
from database import get_database_url, test_connection, initialize_schema, get_table_counts, DatabaseConfigurationError

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

with st.sidebar:
    st.markdown("## 🎯 LeadFlow AI")
    st.caption("Intelligent lead workflow")
    st.divider()
    page = st.radio("Navigation", ["Overview", "Lead Intake", "All Leads", "AI Qualification", "Assignment & Follow-up", "Workflow History", "Database Setup"], index=0)
    st.divider()
    st.caption("Phase 2 · Database foundation")
    st.caption("Demo environment · Synthetic data only")

st.markdown("""<div class="hero"><h1>LeadFlow AI</h1><p>From form submission to qualified lead, assigned owner, and reviewed follow-up draft.</p></div>""", unsafe_allow_html=True)

if page == "Database Setup":
    st.subheader("Neon PostgreSQL connection")
    st.write("Configure your Neon connection string in Streamlit Community Cloud Secrets, then test the connection and create the initial LeadFlow AI tables.")
    st.warning("Never paste your database connection string into this page, chat, or GitHub. Add it only in Streamlit's Secrets settings.")
    st.write("**Connection string configured:** " + ("Yes" if get_database_url() else "No"))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Test database connection", type="primary", use_container_width=True):
            try: st.success(test_connection())
            except DatabaseConfigurationError as exc: st.error(str(exc))
            except Exception: st.error("Connection failed. Check the Neon connection string, database status, and SSL settings. Sensitive details are hidden.")
    with c2:
        if st.button("Create / verify tables", use_container_width=True):
            try:
                initialize_schema()
                st.success("Database schema is ready. Required tables were created or already existed.")
            except DatabaseConfigurationError as exc: st.error(str(exc))
            except Exception: st.error("Schema setup failed. Test the connection and check the Neon connection string and database permissions.")
    st.markdown("### Tables in this phase")
    st.dataframe([
        {"Table":"leads", "Purpose":"Submitted lead/contact details and workflow status"},
        {"Table":"sales_owners", "Purpose":"Sales owner names, email, specialization, and availability"},
        {"Table":"qualification_results", "Purpose":"Future AI qualification scores, categories, and explanations"},
        {"Table":"email_drafts", "Purpose":"Future follow-up drafts and review status"},
        {"Table":"workflow_events", "Purpose":"Chronological audit trail of workflow events"},
    ], use_container_width=True, hide_index=True)
    st.markdown("### Table record counts")
    if st.button("Refresh database counts"):
        try:
            st.session_state["db_counts"] = get_table_counts()
            st.success("Counts refreshed from Neon.")
        except DatabaseConfigurationError as exc: st.error(str(exc))
        except Exception: st.error("Could not read the tables. Initialize the schema and check the connection.")
    if "db_counts" in st.session_state: st.json(st.session_state["db_counts"])

elif page == "Overview":
    st.subheader("Sales pipeline overview")
    st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y, %H:%M')} · Placeholder metrics")
    cols = st.columns(4)
    for col, (label, value, note) in zip(cols, [("Total leads","24","Demo records"),("Qualified","15","AI qualification not connected"),("High priority","6","Placeholder value"),("Needs review","3","Placeholder value")]):
        with col:
            col.metric(label, value)
            col.caption(note)
    st.subheader("Recent workflow activity")
    st.dataframe([
        {"Time":"10:02","Lead":"LF-DEMO-004","Event":"Follow-up draft prepared","Status":"Demo"},
        {"Time":"10:01","Lead":"LF-DEMO-003","Event":"Owner assigned","Status":"Demo"},
        {"Time":"09:58","Lead":"LF-DEMO-002","Event":"Qualification completed","Status":"Demo"},
        {"Time":"09:54","Lead":"LF-DEMO-001","Event":"Form submitted","Status":"Demo"},
    ], use_container_width=True, hide_index=True)
    st.caption("These rows are illustrative and are not stored in Neon.")
elif page == "Lead Intake":
    st.subheader("Lead intake")
    st.write("The functional lead submission form will be implemented in Phase 3.")
    with st.form("phase2_intake_preview"):
        st.text_input("Full name", placeholder="e.g., Ahmed Khan", disabled=True)
        st.text_input("Work email", placeholder="name@company.com", disabled=True)
        st.text_input("Company", placeholder="Company name", disabled=True)
        st.text_area("What does the prospect need?", disabled=True)
        st.form_submit_button("Form available in Phase 3", disabled=True)
    st.warning("Preview only. Submissions are not accepted or saved yet.")
elif page == "All Leads":
    st.subheader("All leads")
    st.write("Lead records and search will be connected in Phase 3.")
    st.dataframe([
        {"Lead ID":"LF-DEMO-001","Name":"Ahmed Khan","Company":"Example Biotech","Priority":"High","Status":"Demo"},
        {"Lead ID":"LF-DEMO-002","Name":"Mina Shah","Company":"Northstar Labs","Priority":"Medium","Status":"Demo"},
        {"Lead ID":"LF-DEMO-003","Name":"Omar Ali","Company":"BrightPath Health","Priority":"Low","Status":"Demo"},
    ], use_container_width=True, hide_index=True)
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
    st.write("Persistent workflow events will be written in later phases.")
    st.dataframe([
        {"Step":"Application shell","Result":"Available","Details":"Phase 1 UI is loaded"},
        {"Step":"Neon connection","Result":"Phase 2","Details":"Configure and test from Database Setup"},
        {"Step":"AI qualification","Result":"Not configured","Details":"Planned for Phase 5"},
    ], use_container_width=True, hide_index=True)

st.divider()
st.markdown('<p class="small-note">LeadFlow AI · Phase 2 · Database setup is available; lead workflow integrations are not active yet.</p>', unsafe_allow_html=True)

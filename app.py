import streamlit as st
from datetime import datetime

st.set_page_config(page_title="LeadFlow AI", page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

# Phase 1 UI refinement. Synthetic placeholders only; no database/AI integrations yet.
st.markdown(r"""
<style>
:root { color-scheme: dark; }
.stApp { background: linear-gradient(135deg,#0b1020 0%,#14152d 55%,#21143a 100%); color:#f4f2ff; }
[data-testid="stHeader"] { background:#0b1020 !important; border-bottom:1px solid rgba(167,139,250,.18); }
[data-testid="stToolbar"] { right:1rem; }
[data-testid="stDecoration"] { background-image:none !important; }
[data-testid="stSidebar"] { background:#101326; border-right:1px solid rgba(167,139,250,.28); }
[data-testid="stSidebar"] * { color:#e9e7ff; }
.stApp p,.stApp label,.stApp li,.stApp [data-testid="stMarkdownContainer"] { color:#e9e7ff; }
h1,h2,h3,h4 { color:#fff !important; letter-spacing:-.02em; }
[data-testid="stCaptionContainer"] p { color:#b8b5d8 !important; }
.hero { padding:1.4rem 1.6rem; border:1px solid rgba(167,139,250,.4); border-radius:18px; background:linear-gradient(120deg,rgba(124,58,237,.25),rgba(59,130,246,.13)); margin-bottom:1.2rem; box-shadow:0 12px 35px rgba(0,0,0,.12); }
.hero h1 { margin-bottom:.35rem; color:#fff !important; }
.hero p { color:#dedaff !important; margin-bottom:0; }
.small-note { color:#b8b5d8 !important; font-size:.84rem; }
div[data-testid="stMetric"] { background:rgba(23,27,53,.92); border:1px solid rgba(167,139,250,.35); padding:1rem; border-radius:14px; box-shadow:0 5px 18px rgba(0,0,0,.1); }
div[data-testid="stMetricLabel"] { color:#c9c5eb !important; }
div[data-testid="stMetricValue"] { color:#fff !important; }
div[data-testid="stMetricDelta"] { color:#c4b5fd !important; }
.stApp input,.stApp textarea,.stApp [data-baseweb="select"] > div,.stApp [data-baseweb="input"] > div { background-color:#171b35 !important; color:#f4f2ff !important; border-color:#62558f !important; border-radius:10px !important; }
.stApp input::placeholder,.stApp textarea::placeholder { color:#aaa5c9 !important; opacity:1 !important; }
.stApp [data-baseweb="select"] *,.stApp [data-baseweb="input"] * { color:#f4f2ff !important; }
.stApp input:disabled,.stApp textarea:disabled { background-color:#20243e !important; color:#b7b3d1 !important; border:1px solid #4c456e !important; opacity:.9; }
.stApp input:focus,.stApp textarea:focus { border-color:#a78bfa !important; box-shadow:0 0 0 1px #a78bfa !important; }
.stApp button[kind="secondary"],.stApp button[kind="primary"],.stApp [data-testid="stFormSubmitButton"] button { border:1px solid #8b5cf6 !important; border-radius:10px !important; }
.stApp button[kind="primary"],.stApp [data-testid="stFormSubmitButton"] button { background:linear-gradient(90deg,#7c3aed,#5b5bd6) !important; color:#fff !important; }
.stApp [data-testid="stDataFrame"],.stApp [data-testid="stTable"] { border:1px solid #514875; border-radius:12px; overflow:hidden; }
.stApp [data-testid="stDataFrame"] iframe { background:#171b35 !important; }
.stApp table { background:#171b35 !important; color:#f0edff !important; border-collapse:collapse !important; }
.stApp thead tr th { background:#24203f !important; color:#e9e3ff !important; border-color:#514875 !important; }
.stApp tbody tr td { background:#171b35 !important; color:#f0edff !important; border-color:#393353 !important; }
.stApp hr { border-color:rgba(167,139,250,.22); }
div[data-testid="stAlert"] { border-radius:12px; border:1px solid rgba(167,139,250,.28); }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## 🎯 LeadFlow AI")
    st.caption("Intelligent lead workflow")
    st.divider()
    page = st.radio("Navigation", ["Overview", "Lead Intake", "All Leads", "AI Qualification", "Assignment & Follow-up", "Workflow History"], index=0)
    st.divider()
    st.caption("Phase 1 · Application shell")
    st.caption("Demo environment · Synthetic data only")

st.markdown("""
<div class="hero"><h1>LeadFlow AI</h1><p>From form submission to qualified lead, assigned owner, and reviewed follow-up draft.</p></div>
""", unsafe_allow_html=True)
st.info("Phase 1 foundation is running. This version uses placeholder demo values only; Neon database connectivity, AI qualification, and workflow processing will be added in later phases.")

if page == "Overview":
    st.subheader("Sales pipeline overview")
    st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y, %H:%M')} · Placeholder metrics")
    cols = st.columns(4)
    metrics = [("Total leads", "24", "+ demo records"), ("Qualified", "15", "AI qualification not connected"), ("High priority", "6", "Placeholder value"), ("Needs review", "3", "Placeholder value")]
    for col, (label, value, note) in zip(cols, metrics):
        with col: st.metric(label, value, help=note)
    st.subheader("Recent workflow activity")
    st.dataframe([
        {"Time":"10:02","Lead":"LF-DEMO-004","Event":"Follow-up draft prepared","Status":"Demo"},
        {"Time":"10:01","Lead":"LF-DEMO-003","Event":"Owner assigned","Status":"Demo"},
        {"Time":"09:58","Lead":"LF-DEMO-002","Event":"Qualification completed","Status":"Demo"},
        {"Time":"09:54","Lead":"LF-DEMO-001","Event":"Form submitted","Status":"Demo"}], use_container_width=True, hide_index=True)
    st.caption("These rows are illustrative and are not stored in a database.")
elif page == "Lead Intake":
    st.subheader("Lead intake")
    st.write("The lead submission form will be implemented in Phase 3.")
    with st.form("phase1_intake_preview"):
        st.text_input("Full name", placeholder="e.g., Ahmed Khan", disabled=True)
        st.text_input("Work email", placeholder="name@company.com", disabled=True)
        st.text_input("Company", placeholder="Company name", disabled=True)
        st.text_area("What does the prospect need?", disabled=True)
        st.form_submit_button("Form available in Phase 3", disabled=True)
    st.warning("This is a visual preview only. Submissions are not accepted or saved yet.")
elif page == "All Leads":
    st.subheader("All leads")
    st.write("The searchable lead table will be connected to Neon PostgreSQL in later phases.")
    st.dataframe([
        {"Lead ID":"LF-DEMO-001","Name":"Ahmed Khan","Company":"Example Biotech","Priority":"High","Status":"Demo"},
        {"Lead ID":"LF-DEMO-002","Name":"Mina Shah","Company":"Northstar Labs","Priority":"Medium","Status":"Demo"},
        {"Lead ID":"LF-DEMO-003","Name":"Omar Ali","Company":"BrightPath Health","Priority":"Low","Status":"Demo"}], use_container_width=True, hide_index=True)
    st.caption("All names and companies above are synthetic examples.")
elif page == "AI Qualification":
    st.subheader("AI qualification")
    st.write("This area will display the qualification score, category, reasons, missing information, and recommended next action.")
    st.info("Groq integration and structured-output validation are planned for Phase 5.")
elif page == "Assignment & Follow-up":
    st.subheader("Assignment & follow-up")
    left, right = st.columns(2)
    with left:
        st.markdown("### Sales owner assignment")
        st.write("Specialization, availability, and workload-aware assignment will be added in Phase 6.")
    with right:
        st.markdown("### Email draft review")
        st.write("Email drafting and human review controls will be added in Phase 7.")
    st.info("No emails are sent by this application.")
elif page == "Workflow History":
    st.subheader("Workflow history")
    st.write("A persistent audit timeline will be connected to the database in later phases.")
    st.dataframe([
        {"Step":"Application shell","Result":"Available","Details":"Phase 1 UI is loaded"},
        {"Step":"Neon connection","Result":"Not configured","Details":"Planned for Phase 2"},
        {"Step":"AI qualification","Result":"Not configured","Details":"Planned for Phase 5"}], use_container_width=True, hide_index=True)

st.divider()
st.markdown('<p class="small-note">LeadFlow AI · Phase 1 starter · Synthetic demo data only · No CRM or AI integrations active</p>', unsafe_allow_html=True)

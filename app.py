import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="LeadFlow AI",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Phase 1 shell: synthetic placeholder data only.
# Database and AI integrations will be added in later phases.

st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(135deg, #0b1020 0%, #14152d 55%, #21143a 100%);
        color: #f4f2ff;
    }
    [data-testid="stSidebar"] {
        background: #101326;
        border-right: 1px solid rgba(167, 139, 250, 0.22);
    }
    .hero {
        padding: 1.4rem 1.6rem;
        border: 1px solid rgba(167, 139, 250, 0.35);
        border-radius: 18px;
        background: linear-gradient(120deg, rgba(124, 58, 237, 0.22), rgba(59, 130, 246, 0.10));
        margin-bottom: 1.2rem;
    }
    .hero h1 { margin-bottom: 0.35rem; color: #ffffff; }
    .hero p { color: #d8d5f0; margin-bottom: 0; }
    .metric-card {
        padding: 1rem 1.1rem;
        border: 1px solid rgba(167, 139, 250, 0.25);
        border-radius: 14px;
        background: rgba(23, 27, 53, 0.82);
        min-height: 118px;
    }
    .metric-label { color: #b9b6d8; font-size: 0.88rem; }
    .metric-value { color: #ffffff; font-size: 2rem; font-weight: 700; margin-top: 0.35rem; }
    .small-note { color: #aaa7c8; font-size: 0.84rem; }
    div[data-testid="stMetric"] {
        background: rgba(23, 27, 53, 0.82);
        border: 1px solid rgba(167, 139, 250, 0.25);
        padding: 1rem;
        border-radius: 14px;
    }
    div[data-testid="stMetricLabel"] { color: #c5c1e4; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## 🎯 LeadFlow AI")
    st.caption("Intelligent lead workflow")
    st.divider()
    page = st.radio(
        "Navigation",
        ["Overview", "Lead Intake", "All Leads", "AI Qualification", "Assignment & Follow-up", "Workflow History"],
        index=0,
    )
    st.divider()
    st.caption("Phase 1 · Application shell")
    st.caption("Demo environment · Synthetic data only")

st.markdown(
    """
    <div class="hero">
      <h1>LeadFlow AI</h1>
      <p>From form submission to qualified lead, assigned owner, and reviewed follow-up draft.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "Phase 1 foundation is running. This version uses placeholder demo values only; "
    "Neon database connectivity, AI qualification, and workflow processing will be added in later phases."
)

if page == "Overview":
    st.subheader("Sales pipeline overview")
    st.caption(f"Last refreshed: {datetime.now().strftime('%d %b %Y, %H:%M')} · Placeholder metrics")

    cols = st.columns(4)
    metrics = [
        ("Total leads", "24", "+ demo records"),
        ("Qualified", "15", "AI qualification not connected"),
        ("High priority", "6", "Placeholder value"),
        ("Needs review", "3", "Placeholder value"),
    ]
    for col, (label, value, note) in zip(cols, metrics):
        with col:
            st.metric(label, value)
            st.caption(note)

    st.subheader("Recent workflow activity")
    st.dataframe(
        [
            {"Time": "10:02", "Lead": "LF-DEMO-004", "Event": "Follow-up draft prepared", "Status": "Demo"},
            {"Time": "10:01", "Lead": "LF-DEMO-003", "Event": "Owner assigned", "Status": "Demo"},
            {"Time": "09:58", "Lead": "LF-DEMO-002", "Event": "Qualification completed", "Status": "Demo"},
            {"Time": "09:54", "Lead": "LF-DEMO-001", "Event": "Form submitted", "Status": "Demo"},
        ],
        use_container_width=True,
        hide_index=True,
    )
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
    st.dataframe(
        [
            {"Lead ID": "LF-DEMO-001", "Name": "Ahmed Khan", "Company": "Example Biotech", "Priority": "High", "Status": "Demo"},
            {"Lead ID": "LF-DEMO-002", "Name": "Mina Shah", "Company": "Northstar Labs", "Priority": "Medium", "Status": "Demo"},
            {"Lead ID": "LF-DEMO-003", "Name": "Omar Ali", "Company": "BrightPath Health", "Priority": "Low", "Status": "Demo"},
        ],
        use_container_width=True,
        hide_index=True,
    )
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
    st.dataframe(
        [
            {"Step": "Application shell", "Result": "Available", "Details": "Phase 1 UI is loaded"},
            {"Step": "Neon connection", "Result": "Not configured", "Details": "Planned for Phase 2"},
            {"Step": "AI qualification", "Result": "Not configured", "Details": "Planned for Phase 5"},
        ],
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.markdown(
    '<p class="small-note">LeadFlow AI · Phase 1 starter · Synthetic demo data only · No CRM or AI integrations active</p>',
    unsafe_allow_html=True,
)

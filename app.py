
import json
import os
import re

import streamlit as st
from groq import Groq

from database import *


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="LeadFlow AI",
    page_icon="🟣",
    layout="wide"
)

st.markdown(
    """
    <style>
        .stApp {
            background: linear-gradient(
                135deg,
                #10101d,
                #17132b,
                #20143b
            );
            color: #f5f3ff;
        }

        [data-testid="stSidebar"] {
            background: #11101d;
        }

        h1, h2, h3, p, label {
            color: #f5f3ff;
        }

        div[data-testid="stMetricValue"] {
            color: #d8b4fe;
        }

        .stButton > button {
            border-radius: 10px;
            border: 1px solid #8b5cf6;
        }
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# APPLICATION HEADER
# ============================================================

st.title("🟣 LeadFlow AI")

st.caption(
    "Lead intake, duplicate intelligence, and AI-assisted qualification"
)


# ============================================================
# SESSION STATE
# ============================================================

session_defaults = {
    "pending_lead": None,
    "pending_matches": [],
    "confirm_possible_duplicate": False,
    "save_message": None,
    "last_qualification": None
}

for key, value in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ============================================================
# SIDEBAR NAVIGATION
# ============================================================

with st.sidebar:

    st.markdown("## LeadFlow AI")

    page = st.radio(
        "Workspace",
        [
            "Overview",
            "Lead Intake",
            "All Leads",
            "AI Qualification",
            "Workflow History",
            "Database Setup"
        ]
    )

    st.caption("AI recommendations require human review.")


# ============================================================
# DATABASE CONNECTION
# ============================================================

try:

    if not get_database_url():

        st.warning(
            "Add NEON_DATABASE_URL in "
            "Streamlit Community Cloud → App settings → Secrets."
        )

        st.stop()

    if not test_connection():

        st.error(
            "Could not connect to Neon. "
            "Please check your NEON_DATABASE_URL."
        )

        st.stop()

    initialize_schema()

except Exception as e:

    st.error(f"Database setup failed: {e}")

    st.stop()


# ============================================================
# AI LEAD QUALIFICATION FUNCTION
# ============================================================

def qualify(lead):

    key = None

    try:
        key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        pass

    key = key or os.getenv("GROQ_API_KEY")

    if not key:

        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it in "
            "Streamlit Community Cloud → App settings → Secrets. "
            "Never put it in GitHub or chat."
        )

    model = None

    try:
        model = st.secrets.get("GROQ_MODEL")
    except Exception:
        pass

    model = (
        model
        or os.getenv("GROQ_MODEL")
        or "openai/gpt-oss-120b"
    )

    fields = [
        "lead_reference",
        "contact_name",
        "email",
        "company",
        "website",
        "job_title",
        "industry",
        "country",
        "company_size",
        "budget",
        "timeline",
        "description"
    ]

    data = {
        field: lead.get(field)
        for field in fields
    }

    prompt = f"""
Assess this B2B sales lead using only the supplied facts.
Do not invent details.

Return valid JSON only with these fields:

- score: integer from 0 to 100
- category: high_fit, medium_fit, low_fit, or needs_review
- priority: urgent, high, medium, or low
- reasoning: string
- missing_information: array of strings
- recommended_next_action: string
- human_review_required: boolean

Use needs_review when evidence is insufficient.

This is decision support, not a final decision.

Lead:
{json.dumps(data, default=str)}
"""

    response = Groq(api_key=key).chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a cautious sales qualification assistant. "
                    "Return valid JSON only."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
        max_tokens=900
    )

    raw = re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        response.choices[0].message.content or "",
        flags=re.I
    )

    match = re.search(r"\{.*\}", raw, re.S)

    if not match:

        raise ValueError(
            "The AI response was not valid JSON. Please retry."
        )

    result = json.loads(match.group())

    allowed_categories = {
        "high_fit",
        "medium_fit",
        "low_fit",
        "needs_review"
    }

    allowed_priorities = {
        "urgent",
        "high",
        "medium",
        "low"
    }

    category = str(
        result.get("category", "needs_review")
    ).lower()

    priority = str(
        result.get("priority", "medium")
    ).lower()

    if category not in allowed_categories:
        category = "needs_review"

    if priority not in allowed_priorities:
        priority = "medium"

    try:

        score = max(
            0,
            min(100, int(result.get("score", 0)))
        )

    except (ValueError, TypeError):

        score = 0
        category = "needs_review"

    missing = result.get("missing_information", [])

    if not isinstance(missing, list):
        missing = [str(missing)]

    return {
        "model_name": model,
        "score": score,
        "category": category,
        "priority": priority,
        "reasoning": str(
            result.get("reasoning", "No explanation supplied.")
        ),
        "missing_information": [
            str(item) for item in missing
        ],
        "recommended_next_action": str(
            result.get(
                "recommended_next_action",
                "Review this lead manually."
            )
        ),
        "human_review_required": bool(
            result.get("human_review_required", True)
        )
    }


# ============================================================
# PAGE 1: OVERVIEW
# ============================================================

if page == "Overview":

    st.subheader("Overview")

    leads = get_leads()
    counts = get_table_counts()

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total Leads",
        counts["leads"]
    )

    col2.metric(
        "Qualification Results",
        counts["qualification_results"]
    )

    col3.metric(
        "Workflow Events",
        counts["workflow_events"]
    )

    col4.metric(
        "Needs Review",
        sum(
            lead.get("status") == "needs_review"
            for lead in leads
        )
    )

    st.divider()

    st.subheader("Recent Leads")

    if leads:

        st.dataframe(
            leads[:10],
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No leads yet. Add your first lead from Lead Intake."
        )

    st.caption(
        "Potential duplicates are never merged automatically. "
        "AI recommendations are advisory."
    )


# ============================================================
# PAGE 2: LEAD INTAKE
# ============================================================

elif page == "Lead Intake":

    st.subheader("Lead Intake")

    if st.session_state.save_message:

        st.success(st.session_state.save_message)

        st.session_state.save_message = None

    with st.form(
        "lead_form",
        clear_on_submit=False
    ):

        col1, col2 = st.columns(2)

        with col1:

            name = st.text_input("Contact name *")

            email = st.text_input("Business email *")

            company = st.text_input("Company *")

            website = st.text_input("Website")

            title = st.text_input("Job title")

        with col2:

            industry = st.text_input("Industry")

            country = st.text_input("Country")

            size = st.selectbox(
                "Company size",
                [
                    "",
                    "1-10",
                    "11-50",
                    "51-200",
                    "201-1000",
                    "1000+"
                ]
            )

            budget = st.text_input("Budget")

            timeline = st.selectbox(
                "Buying timeline",
                [
                    "",
                    "Immediate",
                    "Within 1 month",
                    "1-3 months",
                    "3-6 months",
                    "6+ months",
                    "Unknown"
                ]
            )

        desc = st.text_area(
            "Lead notes / business need"
        )

        submitted = st.form_submit_button(
            "Check lead and continue",
            type="primary"
        )

    if submitted:

        lead = {
            "contact_name": name.strip(),
            "email": email.strip(),
            "company": company.strip(),
            "website": website.strip(),
            "job_title": title.strip(),
            "industry": industry.strip(),
            "country": country.strip(),
            "company_size": size,
            "budget": budget.strip(),
            "timeline": timeline,
            "description": desc.strip()
        }

        missing = [
            label
            for label, value in [
                ("Contact name", lead["contact_name"]),
                ("Email", lead["email"]),
                ("Company", lead["company"])
            ]
            if not value
        ]

        if missing:

            st.error(
                "Please complete required fields: "
                + ", ".join(missing)
            )

        elif (
            "@" not in lead["email"]
            or "." not in lead["email"].split("@")[-1]
        ):

            st.error("Please enter a valid email address.")

        else:

            try:

                matches = find_potential_duplicates(lead)

                exact_matches = [
                    item
                    for item in matches
                    if item.get("match_type") == "exact_email"
                ]

                if exact_matches:

                    st.error(
                        "A lead with this email already exists. "
                        "Exact email duplicates cannot be saved."
                    )

                    st.dataframe(
                        exact_matches,
                        use_container_width=True,
                        hide_index=True
                    )

                    st.session_state.pending_lead = None
                    st.session_state.pending_matches = []

                elif matches:

                    st.session_state.pending_lead = lead

                    st.session_state.pending_matches = matches

                    st.session_state.confirm_possible_duplicate = False

                    st.success(
                        "Potential matches found. Review them below, "
                        "then confirm if this is a separate lead."
                    )

                else:

                    reference = create_lead(lead)

                    st.session_state.save_message = (
                        "Lead saved successfully. "
                        f"Reference: {reference}"
                    )

                    st.rerun()

            except Exception as e:

                st.error(f"Lead check/save failed: {e}")

    # Potential duplicate confirmation

    if st.session_state.pending_lead:

        st.warning("Possible duplicates require review.")

        st.dataframe(
            st.session_state.pending_matches,
            use_container_width=True,
            hide_index=True
        )

        st.checkbox(
            "I reviewed the matches and confirm this is a separate lead.",
            key="confirm_possible_duplicate"
        )

        if st.button(
            "Confirm and save lead",
            type="primary"
        ):

            if not st.session_state.confirm_possible_duplicate:

                st.error(
                    "Tick the confirmation box after reviewing matches."
                )

            else:

                try:

                    reference = create_lead(
                        st.session_state.pending_lead
                    )

                    st.session_state.save_message = (
                        "Confirmed lead saved successfully. "
                        f"Reference: {reference}"
                    )

                    st.session_state.pending_lead = None
                    st.session_state.pending_matches = []
                    st.session_state.confirm_possible_duplicate = False

                    st.rerun()

                except Exception as e:

                    st.error(
                        f"Could not save confirmed lead: {e}"
                    )


# ============================================================
# PAGE 3: ALL LEADS
# ============================================================

elif page == "All Leads":

    st.subheader("All Leads")

    leads = get_leads()

    if not leads:

        st.info("No leads saved yet.")

    else:

        search_query = st.text_input(
            "Search leads",
            placeholder="Name, email, company, reference"
        )

        statuses = sorted({
            str(lead.get("status", "new"))
            for lead in leads
        })

        selected_status = st.selectbox(
            "Filter by status",
            ["All statuses"] + statuses
        )

        filtered_leads = [
            lead
            for lead in leads
            if (
                search_query.lower()
                in " ".join(
                    str(lead.get(field, ""))
                    for field in [
                        "lead_reference",
                        "contact_name",
                        "email",
                        "company"
                    ]
                ).lower()
            )
            and (
                selected_status == "All statuses"
                or lead.get("status") == selected_status
            )
        ]

        st.dataframe(
            filtered_leads,
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            f"Showing {len(filtered_leads)} of {len(leads)} leads."
        )


# ============================================================
# PAGE 4: AI QUALIFICATION
# ============================================================

elif page == "AI Qualification":

    st.subheader("Phase 5 — AI Lead Qualification")

    leads = get_leads()

    if not leads:

        st.info("Add a lead first using Lead Intake.")

    else:

        choices = {
            (
                f"{lead.get('lead_reference')} — "
                f"{lead.get('contact_name')} / "
                f"{lead.get('company')}"
            ): lead
            for lead in leads
        }

        selected_label = st.selectbox(
            "Select a lead to qualify",
            list(choices.keys())
        )

        lead = choices[selected_label]

        # Display lead details in a readable format

        with st.expander(
            "Lead Details",
            expanded=True
        ):

            details = [
                ("Email", lead.get("email")),
                ("Industry", lead.get("industry")),
                ("Job Title", lead.get("job_title")),
                ("Country", lead.get("country")),
                ("Company Size", lead.get("company_size")),
                ("Budget", lead.get("budget")),
                ("Buying Timeline", lead.get("timeline")),
                (
                    "Business Need / Description",
                    lead.get("description")
                )
            ]

            col1, col2 = st.columns(2)

            for index, (label, value) in enumerate(details):

                target_col = (
                    col1 if index % 2 == 0 else col2
                )

                with target_col:

                    st.markdown(f"**{label}**")

                    st.write(
                        value
                        if value not in (None, "")
                        else "Not provided"
                    )

        # Run AI qualification

        if st.button(
            "Qualify selected lead with AI",
            type="primary"
        ):

            with st.spinner(
                "Groq is assessing the lead..."
            ):

                try:

                    result = qualify(lead)

                    save_qualification_result(
                        lead["id"],
                        result
                    )

                    update_lead_qualification(
                        lead["id"],
                        result["category"],
                        result["priority"]
                    )

                    st.session_state.last_qualification = {
                        "lead_reference": lead["lead_reference"],
                        **result
                    }

                    st.success(
                        "Qualification saved to Neon. "
                        "Review the recommendation before acting."
                    )

                except Exception as e:

                    st.error(
                        f"Qualification failed; "
                        f"no result was saved: {e}"
                    )

        # Latest AI assessment

        last = st.session_state.last_qualification

        if (
            last
            and last.get("lead_reference")
            == lead.get("lead_reference")
        ):

            st.markdown("### Latest AI Assessment")

            col1, col2, col3 = st.columns(3)

            col1.metric(
                "Fit Score",
                f"{last['score']}/100"
            )

            col2.metric(
                "Category",
                last["category"].replace("_", " ").title()
            )

            col3.metric(
                "Priority",
                last["priority"].title()
            )

            st.write("**Reasoning**")

            st.write(last["reasoning"])

            st.write("**Missing Information**")

            if last["missing_information"]:

                for item in last["missing_information"]:
                    st.write(f"- {item}")

            else:

                st.write(
                    "No key missing information identified."
                )

            st.write("**Recommended Next Action**")

            st.info(last["recommended_next_action"])

            if last["human_review_required"]:

                st.warning("Human review required: Yes")

            else:

                st.warning(
                    "AI marked review optional. "
                    "Verify the recommendation before taking action."
                )

        # Saved qualification history

        history = get_qualification_results(
            lead["id"]
        )

        if history:

            st.markdown("### Saved Qualification History")

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True
            )


# ============================================================
# PAGE 5: WORKFLOW HISTORY
# ============================================================

elif page == "Workflow History":

    st.subheader("Workflow History")

    events = get_workflow_events()

    if events:

        st.dataframe(
            events,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info("No workflow events recorded yet.")


# ============================================================
# PAGE 6: DATABASE SETUP
# ============================================================

elif page == "Database Setup":

    st.subheader("Database Setup")

    st.success("Connected to Neon PostgreSQL.")

    counts = get_table_counts()

    table_data = [
        {
            "Table": table_name,
            "Records": record_count
        }
        for table_name, record_count in counts.items()
    ]

    st.dataframe(
        table_data,
        use_container_width=True,
        hide_index=True
    )

    st.caption(
        "Expected tables: leads, sales_owners, "
        "qualification_results, email_drafts, workflow_events."
    )


import json
import os
import re

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
    get_workflow_events,
    save_qualification_result,
    update_lead_qualification,
    get_qualification_results,
    get_sales_owners,
    create_sales_owner,
    update_sales_owner_availability,
    get_owner_workloads,
    assign_lead_automatically,
    assign_lead_owner,
    unassign_lead_owner,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="LeadFlow AI",
    page_icon="🟣",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #10101d, #17132b, #20143b);
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

div[data-testid="stDataFrame"] {
    border: 1px solid #39304f;
}
</style>
""", unsafe_allow_html=True)


# ============================================================
# APPLICATION HEADER AND NAVIGATION
# ============================================================

st.title("🟣 LeadFlow AI")

st.caption(
    "AI-powered lead qualification, intelligent owner assignment, "
    "and follow-up workflow"
)

SESSION_DEFAULTS = {
    "pending_lead": None,
    "pending_matches": [],
    "confirm_possible_duplicate": False,
    "save_message": None,
    "last_qualification": None,
    "assignment_message": None,
}

for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


with st.sidebar:
    st.markdown("## LeadFlow AI")

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
        ]
    )

    st.caption("AI recommendations require human review.")


# ============================================================
# DATABASE CONNECTION
# ============================================================

try:
    get_database_url()

    connection_ok, connection_message = test_connection()

    if not connection_ok:
        st.error(
            f"Could not connect to Neon PostgreSQL: {connection_message}"
        )
        st.stop()

    initialize_schema()

except Exception as exc:
    st.error(f"Database setup failed: {exc}")
    st.stop()


# ============================================================
# GROQ AI QUALIFICATION
# ============================================================

def qualify_lead(lead):

    api_key = None

    try:
        api_key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        pass

    api_key = api_key or os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it in Streamlit Cloud secrets. "
            "Do not put your API key in GitHub."
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

    facts = {
        key: lead.get(key)
        for key in fields
    }

    prompt = f"""
Assess this B2B sales lead using only the supplied facts.
Do not invent details.

Return valid JSON only with:

- score: integer from 0 to 100
- category: high_fit, medium_fit, low_fit, or needs_review
- priority: urgent, high, medium, or low
- reasoning: short explanation
- missing_information: array of strings
- recommended_next_action: string
- human_review_required: boolean

Use needs_review when evidence is insufficient.

This is decision support, not a final decision.

Lead facts:
{json.dumps(facts, default=str)}
"""

    response = Groq(api_key=api_key).chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a cautious B2B sales qualification assistant. "
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

    raw = response.choices[0].message.content or ""

    raw = re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        raw,
        flags=re.I
    )

    match = re.search(r"\{.*\}", raw, re.S)

    if not match:
        raise ValueError(
            "The AI response was not valid JSON. Please retry."
        )

    data = json.loads(match.group())

    valid_categories = {
        "high_fit",
        "medium_fit",
        "low_fit",
        "needs_review"
    }

    valid_priorities = {
        "urgent",
        "high",
        "medium",
        "low"
    }

    category = str(
        data.get("category", "needs_review")
    ).lower()

    if category not in valid_categories:
        category = "needs_review"

    priority = str(
        data.get("priority", "medium")
    ).lower()

    if priority not in valid_priorities:
        priority = "medium"

    try:
        score = max(
            0,
            min(100, int(data.get("score", 0)))
        )
    except (TypeError, ValueError):
        score = 0
        category = "needs_review"

    missing = data.get("missing_information", [])

    if not isinstance(missing, list):
        missing = [str(missing)]

    return {
        "model_name": model,
        "score": score,
        "category": category,
        "priority": priority,
        "reasoning": str(
            data.get("reasoning", "No explanation supplied.")
        ),
        "missing_information": [
            str(item) for item in missing
        ],
        "recommended_next_action": str(
            data.get(
                "recommended_next_action",
                "Review this lead manually."
            )
        ),
        "human_review_required": bool(
            data.get("human_review_required", True)
        ),
    }


# ============================================================
# OVERVIEW
# ============================================================

if page == "Overview":

    leads = get_leads()
    counts = get_table_counts()

    unassigned = [
        lead
        for lead in leads
        if lead.get("assigned_owner_id") is None
    ]

    a, b, c, d, e = st.columns(5)

    a.metric("Total leads", counts["leads"])

    b.metric(
        "Qualification results",
        counts["qualification_results"]
    )

    c.metric(
        "Sales owners",
        counts["sales_owners"]
    )

    d.metric(
        "Unassigned leads",
        len(unassigned)
    )

    e.metric(
        "Needs review",
        sum(
            lead.get("status") == "needs_review"
            for lead in leads
        )
    )

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
# LEAD INTAKE
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

        left, right = st.columns(2)

        with left:
            name = st.text_input("Contact name *")
            email = st.text_input("Business email *")
            company = st.text_input("Company *")
            website = st.text_input("Website")
            job_title = st.text_input("Job title")

        with right:
            industry = st.text_input("Industry")
            country = st.text_input("Country")

            company_size = st.selectbox(
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

        description = st.text_area(
            "Lead notes / business need"
        )

        submitted = st.form_submit_button(
            "Check lead and continue",
            type="primary"
        )

    if submitted:

        lead_data = {
            "contact_name": name.strip(),
            "email": email.strip(),
            "company": company.strip(),
            "website": website.strip(),
            "job_title": job_title.strip(),
            "industry": industry.strip(),
            "country": country.strip(),
            "company_size": company_size,
            "budget": budget.strip(),
            "timeline": timeline,
            "description": description.strip(),
        }

        missing = [
            label
            for label, value in [
                ("Contact name", lead_data["contact_name"]),
                ("Email", lead_data["email"]),
                ("Company", lead_data["company"]),
            ]
            if not value
        ]

        if missing:
            st.error(
                "Please complete required fields: "
                + ", ".join(missing)
            )

        elif (
            "@" not in lead_data["email"]
            or "." not in lead_data["email"].split("@")[-1]
        ):
            st.error("Please enter a valid email address.")

        else:

            try:
                matches = find_potential_duplicates(lead_data)

                exact_matches = [
                    row
                    for row in matches
                    if row.get("match_type") == "exact_email"
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

                    st.session_state.pending_lead = lead_data
                    st.session_state.pending_matches = matches
                    st.session_state.confirm_possible_duplicate = False

                    st.warning(
                        "Potential matches found. Review them below, "
                        "then confirm if this is a separate lead."
                    )

                else:

                    new_id = create_lead(lead_data)

                    saved = get_lead_by_id(new_id)

                    reference = (
                        saved["lead_reference"]
                        if saved else str(new_id)
                    )

                    st.session_state.save_message = (
                        "Lead saved successfully. "
                        f"Reference: {reference}"
                    )

                    st.rerun()

            except Exception as exc:
                st.error(
                    f"Lead check/save failed: {exc}"
                )

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
                    new_id = create_lead(
                        st.session_state.pending_lead
                    )

                    saved = get_lead_by_id(new_id)

                    reference = (
                        saved["lead_reference"]
                        if saved else str(new_id)
                    )

                    st.session_state.save_message = (
                        "Confirmed lead saved successfully. "
                        f"Reference: {reference}"
                    )

                    st.session_state.pending_lead = None
                    st.session_state.pending_matches = []
                    st.session_state.confirm_possible_duplicate = False

                    st.rerun()

                except Exception as exc:
                    st.error(
                        f"Could not save confirmed lead: {exc}"
                    )


# ============================================================
# ALL LEADS
# ============================================================

elif page == "All Leads":

    st.subheader("All Leads")

    leads = get_leads()

    if not leads:

        st.info("No leads saved yet.")

    else:

        search = st.text_input(
            "Search leads",
            placeholder="Name, email, company, or reference"
        )

        statuses = sorted({
            str(lead.get("status") or "new")
            for lead in leads
        })

        selected_status = st.selectbox(
            "Filter by status",
            ["All statuses"] + statuses
        )

        filtered = [
            lead
            for lead in leads
            if search.lower() in " ".join(
                str(lead.get(key) or "")
                for key in [
                    "lead_reference",
                    "contact_name",
                    "email",
                    "company",
                    "assigned_owner_name"
                ]
            ).lower()
            and (
                selected_status == "All statuses"
                or lead.get("status") == selected_status
            )
        ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# AI QUALIFICATION
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

        with st.expander(
            "Lead details",
            expanded=True
        ):

            detail_left, detail_right = st.columns(2)

            with detail_left:
                st.write(
                    "**Contact:**",
                    lead.get("contact_name")
                )

                st.write(
                    "**Email:**",
                    lead.get("email")
                )

                st.write(
                    "**Company:**",
                    lead.get("company")
                )

                st.write(
                    "**Industry:**",
                    lead.get("industry")
                )

                st.write(
                    "**Job title:**",
                    lead.get("job_title")
                )

            with detail_right:
                st.write(
                    "**Company size:**",
                    lead.get("company_size")
                )

                st.write(
                    "**Country:**",
                    lead.get("country")
                )

                st.write(
                    "**Budget:**",
                    lead.get("budget")
                )

                st.write(
                    "**Timeline:**",
                    lead.get("timeline")
                )

                st.write(
                    "**Business need:**",
                    lead.get("description")
                )

        if st.button(
            "Qualify selected lead with AI",
            type="primary"
        ):

            with st.spinner("Groq is assessing the lead..."):

                try:
                    result = qualify_lead(lead)

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

                except Exception as exc:
                    st.error(
                        f"Qualification failed: {exc}"
                    )

        latest = st.session_state.last_qualification

        if (
            latest
            and latest.get("lead_reference")
            == lead.get("lead_reference")
        ):

            st.markdown("### Latest AI Assessment")

            x, y, z = st.columns(3)

            x.metric(
                "Fit score",
                f"{latest['score']}/100"
            )

            y.metric(
                "Category",
                latest["category"].replace("_", " ").title()
            )

            z.metric(
                "Priority",
                latest["priority"].title()
            )

            st.write("**Reasoning**")
            st.write(latest["reasoning"])

            st.write("**Missing information**")

            if latest["missing_information"]:

                for item in latest["missing_information"]:
                    st.write(f"- {item}")

            else:
                st.write("No key missing information identified.")

            st.write("**Recommended next action**")

            st.info(
                latest["recommended_next_action"]
            )

            st.warning(
                "Human review required: "
                + (
                    "Yes"
                    if latest["human_review_required"]
                    else "Verify before action."
                )
            )

        history = get_qualification_results(lead["id"])

        if history:

            st.markdown("### Saved Qualification History")

            st.dataframe(
                history,
                use_container_width=True,
                hide_index=True
            )


# ============================================================
# STEP 6 — INTELLIGENT OWNER ASSIGNMENT
# ============================================================

elif page == "Assignment & Follow-up":

    st.subheader(
        "Phase 6 — Intelligent Sales Owner Assignment"
    )

    st.write(
        "LeadFlow AI selects sales representatives using "
        "specialization, availability, and active workload."
    )

    leads = get_leads()
    owners = get_sales_owners()
    workloads = get_owner_workloads()

    unassigned = [
        lead
        for lead in leads
        if lead.get("assigned_owner_id") is None
    ]

    assigned = [
        lead
        for lead in leads
        if lead.get("assigned_owner_id") is not None
    ]

    # --------------------------------------------------------
    # SUMMARY METRICS
    # --------------------------------------------------------

    a, b, c = st.columns(3)

    a.metric(
        "Total sales owners",
        len(owners)
    )

    b.metric(
        "Unassigned leads",
        len(unassigned)
    )

    c.metric(
        "Assigned leads",
        len(assigned)
    )

    if st.session_state.assignment_message:

        st.success(
            st.session_state.assignment_message
        )

        st.session_state.assignment_message = None

    # --------------------------------------------------------
    # 1. SALES OWNER ROSTER
    # --------------------------------------------------------

    st.markdown("### 1. Sales Owner Roster")

    with st.expander(
        "Add a sales owner",
        expanded=not bool(owners)
    ):

        with st.form(
            "add_sales_owner_form",
            clear_on_submit=True
        ):

            owner_name = st.text_input(
                "Full name *"
            )

            owner_email = st.text_input(
                "Email *"
            )

            specialization = st.text_input(
                "Specialization *",
                placeholder=(
                    "e.g. Biotechnology, Healthcare, "
                    "SMB, Enterprise, General"
                )
            )

            capacity = st.number_input(
                "Maximum active leads",
                min_value=1,
                max_value=500,
                value=20,
                step=1
            )

            available = st.checkbox(
                "Available for new leads",
                value=True
            )

            add_owner = st.form_submit_button(
                "Add sales owner",
                type="primary"
            )

        if add_owner:

            try:
                owner_id = create_sales_owner(
                    owner_name,
                    owner_email,
                    specialization,
                    int(capacity),
                    available
                )

                st.success(
                    "Sales owner added successfully. "
                    f"Owner ID: {owner_id}"
                )

                st.rerun()

            except Exception as exc:
                st.error(
                    f"Could not add sales owner: {exc}"
                )

    # --------------------------------------------------------
    # OWNER WORKLOAD TABLE
    # --------------------------------------------------------

    if workloads:

        st.markdown("#### Current Owner Workload")

        workload_view = [
            {
                "Owner": row["full_name"],
                "Specialization": row["specialization"],
                "Available": (
                    "Yes" if row["is_available"] else "No"
                ),
                "Active leads": row["active_leads"],
                "Capacity": row["active_lead_limit"],
                "Remaining capacity": row["remaining_capacity"],
            }
            for row in workloads
        ]

        st.dataframe(
            workload_view,
            use_container_width=True,
            hide_index=True
        )

        # ----------------------------------------------------
        # CHANGE AVAILABILITY
        # ----------------------------------------------------

        availability_options = {
            (
                f"{row['full_name']} — "
                f"{'Available' if row['is_available'] else 'Unavailable'}"
            ): row
            for row in owners
        }

        if availability_options:

            with st.expander(
                "Change owner availability"
            ):

                availability_label = st.selectbox(
                    "Select sales owner",
                    list(availability_options.keys()),
                    key="availability_owner_select"
                )

                availability_owner = availability_options[
                    availability_label
                ]

                new_availability = st.toggle(
                    "Available for new leads",
                    value=bool(
                        availability_owner["is_available"]
                    ),
                    key=(
                        f"availability_toggle_"
                        f"{availability_owner['id']}"
                    )
                )

                if st.button(
                    "Save availability",
                    key="save_availability"
                ):

                    try:
                        update_sales_owner_availability(
                            availability_owner["id"],
                            new_availability
                        )

                        st.success(
                            "Owner availability updated."
                        )

                        st.rerun()

                    except Exception as exc:
                        st.error(
                            f"Could not update availability: {exc}"
                        )

    else:

        st.info(
            "No sales owners have been added yet. "
            "Add at least one owner to enable assignment."
        )

    st.divider()

    # --------------------------------------------------------
    # 2. AUTOMATIC ASSIGNMENT
    # --------------------------------------------------------

    st.markdown("### 2. Automatically Assign Leads")

    if not unassigned:

        st.success(
            "There are currently no unassigned leads."
        )

    elif not owners:

        st.warning(
            "Add sales owners to enable automatic assignment."
        )

    else:

        st.write(
            f"There are **{len(unassigned)}** unassigned "
            "leads waiting for routing."
        )

        if st.button(
            "Automatically Assign All Eligible Leads",
            type="primary",
            key="auto_assign_all"
        ):

            outcomes = []

            progress = st.progress(0)

            for index, item in enumerate(unassigned):

                try:
                    result = assign_lead_automatically(
                        item["id"]
                    )

                    if result["assigned"]:

                        outcomes.append(
                            f"{item['lead_reference']}: "
                            f"{result['message']}"
                        )

                    else:

                        outcomes.append(
                            f"{item['lead_reference']}: "
                            "No eligible owner; left unassigned."
                        )

                except Exception as exc:

                    outcomes.append(
                        f"{item['lead_reference']}: "
                        f"Assignment error — {exc}"
                    )

                progress.progress(
                    (index + 1) / len(unassigned)
                )

            st.session_state.assignment_message = (
                "Assignment run finished. "
                + " | ".join(outcomes)
            )

            st.rerun()

        # ----------------------------------------------------
        # ASSIGN ONE LEAD AUTOMATICALLY
        # ----------------------------------------------------

        st.markdown("#### Assign One Lead")

        lead_options = {
            (
                f"{item['lead_reference']} — "
                f"{item['contact_name']} / "
                f"{item['company']} "
                f"({item.get('priority') or 'unassessed'} priority)"
            ): item
            for item in unassigned
        }

        selected_lead_label = st.selectbox(
            "Select unassigned lead",
            list(lead_options.keys()),
            key="single_auto_lead"
        )

        selected_lead = lead_options[
            selected_lead_label
        ]

        if st.button(
            "Assign Selected Lead Automatically",
            key="auto_assign_one"
        ):

            try:
                result = assign_lead_automatically(
                    selected_lead["id"]
                )

                if result["assigned"]:

                    st.success(result["message"])

                    if result.get("reason"):
                        st.caption(
                            "Assignment reason: "
                            + result["reason"]
                        )

                else:

                    st.warning(result["message"])

                st.rerun()

            except Exception as exc:
                st.error(
                    f"Automatic assignment failed: {exc}"
                )

    st.divider()

    # --------------------------------------------------------
    # 3. MANUAL ASSIGNMENT
    # --------------------------------------------------------

    st.markdown("### 3. Manual Assignment")

    if unassigned and owners:

        manual_lead_options = {
            (
                f"{item['lead_reference']} — "
                f"{item['contact_name']} / "
                f"{item['company']}"
            ): item
            for item in unassigned
        }

        manual_lead_label = st.selectbox(
            "Choose an unassigned lead",
            list(manual_lead_options.keys()),
            key="manual_lead_select"
        )

        manual_lead = manual_lead_options[
            manual_lead_label
        ]

        eligible_owner_rows = [
            row
            for row in workloads
            if (
                row["is_available"]
                and row["remaining_capacity"] > 0
            )
        ]

        if eligible_owner_rows:

            manual_owner_options = {
                (
                    f"{row['full_name']} — "
                    f"{row['specialization']} "
                    f"({row['remaining_capacity']} slots left)"
                ): row
                for row in eligible_owner_rows
            }

            manual_owner_label = st.selectbox(
                "Choose a sales owner",
                list(manual_owner_options.keys()),
                key="manual_owner_select"
            )

            if st.button(
                "Confirm Manual Assignment",
                key="manual_assign_button"
            ):

                try:
                    selected_owner = manual_owner_options[
                        manual_owner_label
                    ]

                    assign_lead_owner(
                        manual_lead["id"],
                        selected_owner["id"]
                    )

                    st.success(
                        "Lead assigned to "
                        f"{selected_owner['full_name']}."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        f"Manual assignment failed: {exc}"
                    )

        else:

            st.info(
                "No available owner has remaining capacity. "
                "Increase capacity or mark an owner available."
            )

    elif not unassigned:

        st.info(
            "No unassigned leads are available for manual assignment."
        )

    else:

        st.info(
            "Add a sales owner before assigning leads."
        )

    st.divider()

    # --------------------------------------------------------
    # 4. ASSIGNED LEADS
    # --------------------------------------------------------

    st.markdown("### 4. Assigned Leads")

    if assigned:

        assigned_view = [
            {
                "Lead reference": item["lead_reference"],
                "Contact": item["contact_name"],
                "Company": item["company"],
                "Priority": item["priority"],
                "Status": item["status"],
                "Assigned owner": (
                    item.get("assigned_owner_name")
                    or "Unknown"
                ),
            }
            for item in assigned
        ]

        st.dataframe(
            assigned_view,
            use_container_width=True,
            hide_index=True
        )

        # ----------------------------------------------------
        # UNASSIGN A LEAD
        # ----------------------------------------------------

        with st.expander(
            "Return an assigned lead to the unassigned queue"
        ):

            assigned_options = {
                (
                    f"{item['lead_reference']} — "
                    f"{item['contact_name']} "
                    f"(Owner: "
                    f"{item.get('assigned_owner_name') or 'Unknown'})"
                ): item
                for item in assigned
            }

            selected_assigned_label = st.selectbox(
                "Select assigned lead",
                list(assigned_options.keys()),
                key="unassign_lead_select"
            )

            selected_assigned = assigned_options[
                selected_assigned_label
            ]

            if st.button(
                "Unassign Selected Lead",
                key="unassign_button"
            ):

                try:
                    unassign_lead_owner(
                        selected_assigned["id"]
                    )

                    st.success(
                        "Lead returned to the unassigned queue."
                    )

                    st.rerun()

                except Exception as exc:
                    st.error(
                        f"Could not unassign lead: {exc}"
                    )

    else:

        st.info(
            "No leads have been assigned yet."
        )

    st.caption(
        "Assignment is rule-based. AI qualification priority is "
        "displayed for context but does not override owner availability "
        "or capacity. No email is sent in this phase."
    )


# ============================================================
# WORKFLOW HISTORY
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

        st.info(
            "No workflow events recorded yet."
        )


# ============================================================
# DATABASE SETUP
# ============================================================

elif page == "Database Setup":

    st.subheader("Database Setup")

    st.success(
        "Connected to Neon PostgreSQL."
    )

    counts = get_table_counts()

    st.dataframe(
        [
            {
                "Table": table,
                "Records": total
            }
            for table, total in counts.items()
        ],
        use_container_width=True,
        hide_index=True
    )

    st.caption(
        "Existing tables: leads, sales_owners, "
        "qualification_results, email_drafts, workflow_events. "
        "This application does not recreate them."
    )


# ============================================================
# FOOTER
# ============================================================

st.divider()

st.caption(
    "LeadFlow AI · Step 6 — Intelligent Sales Owner Assignment · "
    "AI recommendations require human review."
)

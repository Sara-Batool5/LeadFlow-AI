
import streamlit as st

from agent_workflow import run_lead_workflow


# ============================================================
# PAGE HEADER
# ============================================================

st.title("LangGraph Agent Workflow")

st.markdown(
    """
    Run a coordinated lead-processing workflow using specialized AI agents.

    The workflow validates a lead, checks for duplicates, qualifies it,
    attempts sales-owner assignment, and prepares an email draft for review.
    """
)

st.divider()


# ============================================================
# RESULT DISPLAY
# ============================================================

def display_workflow_result(result):
    stage = result.get("stage", "unknown")

    if stage == "validation_failed":
        st.error(
            result.get("error", "Lead validation failed.")
        )
        return

    if stage == "duplicate_review_required":
        st.warning(
            "Possible duplicate leads were found. "
            "The workflow stopped before creating a new record."
        )

        matches = result.get("duplicate_matches", [])

        if matches:
            st.subheader("Potential Matching Leads")
            st.dataframe(
                matches,
                use_container_width=True,
                hide_index=True,
            )

        st.info(
            "Review the matches carefully. If this is genuinely a "
            "different prospect, you can explicitly confirm below."
        )

        return

    if result.get("error"):
        st.error(
            f"Workflow stopped: {result['error']}"
        )

        if result.get("lead_id"):
            st.caption(
                f"Lead ID: {result['lead_id']}"
            )

        return

    if not result.get("lead_id"):
        st.warning(
            "The workflow did not create a lead record."
        )
        return

    st.success(
        "The LangGraph workflow has processed the lead."
    )

    st.subheader("Workflow Results")

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Lead Reference",
        result.get("lead_reference") or str(result["lead_id"]),
    )

    qualification = result.get("qualification") or {}

    col2.metric(
        "AI Lead Score",
        (
            f"{qualification.get('score', '—')}/100"
            if qualification
            else "Not available"
        ),
    )

    col3.metric(
        "Qualification",
        qualification.get("category", "Not available"),
    )

    st.divider()

    # Qualification
    st.subheader("1. AI Qualification")

    if qualification:
        st.markdown("**Reasoning**")
        st.write(
            qualification.get("reasoning", "Not available.")
        )

        st.markdown("**Recommended next action**")
        st.info(
            qualification.get(
                "recommended_next_action",
                "Manual review recommended.",
            )
        )

        missing = qualification.get(
            "missing_information",
            [],
        )

        st.markdown("**Missing information**")

        if missing:
            for item in missing:
                st.write(f"• {item}")
        else:
            st.write("No missing information identified.")

        if qualification.get("human_review_required"):
            st.warning(
                "The qualification agent recommends human review."
            )

    else:
        st.warning(
            "No qualification result is available."
        )

    st.divider()

    # Assignment
    st.subheader("2. Sales Owner Assignment")

    if result.get("assignment_success"):
        owner = result.get("assigned_owner") or {}

        st.success(
            result.get(
                "assignment_message",
                "Sales owner assigned.",
            )
        )

        if owner:
            st.write(
                f"**Assigned owner:** {owner.get('full_name', 'Not available')}"
            )
            st.write(
                f"**Specialization:** {owner.get('specialization', 'Not available')}"
            )

    else:
        st.warning(
            result.get(
                "assignment_message",
                "No sales owner was assigned. The lead remains in the unassigned queue.",
            )
        )

    st.divider()

    # Email draft
    st.subheader("3. Follow-up Email Draft")

    if result.get("draft_id"):
        st.success(
            f"Email draft created successfully. Draft ID: {result['draft_id']}"
        )

        st.markdown("**Subject**")
        st.write(result.get("email_subject", ""))

        st.markdown("**Email body**")
        st.text_area(
            "Generated email",
            value=result.get("email_body", ""),
            height=230,
            disabled=True,
            key=f"workflow_email_{result['draft_id']}",
        )

        st.info(
            "The draft is saved in your existing Email Drafts section. "
            "Open Assignment & Follow-up to edit or approve it. "
            "No email has been sent."
        )

    elif result.get("email_warning"):
        st.warning(
            result["email_warning"]
        )

    elif result.get("stage") == "completed_no_email_consent":
        st.warning(
            result.get(
                "email_warning",
                "Email generation was skipped because contact consent is not recorded.",
            )
        )

    st.divider()

    st.subheader("4. Final Workflow Status")

    if result.get("stage") == "workflow_completed":
        st.success("All workflow stages completed.")

    elif result.get("stage") == "completed_no_email_consent":
        st.success(
            "Lead qualification and assignment workflow completed. "
            "Email generation was skipped because consent was not recorded."
        )

    elif result.get("stage") == "completed_email_warning":
        st.warning(
            "Lead processing completed, but email draft generation needs attention."
        )

    else:
        st.info(
            f"Workflow stage: {result.get('stage', 'unknown')}"
        )


# ============================================================
# LEAD INTAKE FORM
# ============================================================

st.subheader("Submit a Lead to the Agent Workflow")

st.caption(
    "This form runs the complete workflow. It does not replace "
    "your existing Lead Intake page."
)

with st.form("langgraph_lead_form"):
    col1, col2 = st.columns(2)

    with col1:
        contact_name = st.text_input(
            "Contact name *"
        )

        email = st.text_input(
            "Email address *"
        )

        company = st.text_input(
            "Company"
        )

        job_title = st.text_input(
            "Job title"
        )

        website = st.text_input(
            "Company website"
        )

        industry = st.text_input(
            "Industry"
        )

    with col2:
        company_size = st.selectbox(
            "Company size",
            [
                "Not specified",
                "1-10",
                "11-50",
                "51-200",
                "201-500",
                "501-1000",
                "1000+",
            ],
        )

        country = st.text_input(
            "Country"
        )

        source = st.selectbox(
            "Lead source",
            [
                "website_form",
                "LinkedIn",
                "Referral",
                "Email",
                "Event",
                "Other",
            ],
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
            ],
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
            ],
        )

    description = st.text_area(
        "Business need / requirement",
        placeholder=(
            "Describe the prospect's problem, "
            "project requirements, or service interests."
        ),
    )

    consent = st.checkbox(
        "The prospect has consented to be contacted."
    )

    submitted = st.form_submit_button(
        "Run LangGraph Agent Workflow",
        type="primary",
        use_container_width=True,
    )


# ============================================================
# RUN WORKFLOW
# ============================================================

if submitted:
    lead_data = {
        "contact_name": contact_name.strip(),
        "email": email.strip(),
        "company": company.strip(),
        "job_title": job_title.strip(),
        "website": website.strip(),
        "industry": industry.strip(),
        "company_size": (
            None
            if company_size == "Not specified"
            else company_size
        ),
        "country": country.strip(),
        "source": source,
        "budget": (
            None
            if budget == "Not specified"
            else budget
        ),
        "timeline": (
            None
            if timeline == "Not specified"
            else timeline
        ),
        "description": description.strip() or "Not provided",
        "consent_to_contact": consent,
    }

    st.session_state.pop(
        "leadflow_pending_workflow",
        None,
    )

    st.session_state.pop(
        "leadflow_workflow_result",
        None,
    )

    if not contact_name.strip() or not email.strip():
        st.error(
            "Contact name and email address are required."
        )

    elif "@" not in email or "." not in email.split("@")[-1]:
        st.error(
            "Please enter a valid email address."
        )

    else:
        try:
            with st.spinner(
                "LangGraph agents are processing the lead..."
            ):
                result = run_lead_workflow(
                    lead_data,
                    allow_duplicate=False,
                )

            st.session_state[
                "leadflow_workflow_result"
            ] = result

            if result.get("stage") == "duplicate_review_required":
                st.session_state[
                    "leadflow_pending_workflow"
                ] = lead_data

        except Exception as exc:
            st.error(
                f"Unable to run the agent workflow: {exc}"
            )


# ============================================================
# DUPLICATE REVIEW AND EXPLICIT CONFIRMATION
# ============================================================

result = st.session_state.get(
    "leadflow_workflow_result"
)

pending_lead = st.session_state.get(
    "leadflow_pending_workflow"
)

if (
    result
    and result.get("stage") == "duplicate_review_required"
    and pending_lead
):
    display_workflow_result(result)

    if st.button(
        "Confirm This Is a Separate Lead — Continue Workflow",
        type="primary",
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "Continuing workflow after duplicate confirmation..."
            ):
                confirmed_result = run_lead_workflow(
                    pending_lead,
                    allow_duplicate=True,
                )

            st.session_state[
                "leadflow_workflow_result"
            ] = confirmed_result

            st.session_state.pop(
                "leadflow_pending_workflow",
                None,
            )

            st.rerun()

        except Exception as exc:
            st.error(
                f"Unable to continue the workflow: {exc}"
            )


# ============================================================
# FINAL RESULTS
# ============================================================

elif result:
    display_workflow_result(result)

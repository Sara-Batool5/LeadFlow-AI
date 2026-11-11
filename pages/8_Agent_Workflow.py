
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
    makes an AI decision, and routes it to the appropriate next step.
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
        "The lead was created and processed by the workflow."
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

    # --------------------------------------------------------
    # 1. AI QUALIFICATION
    # --------------------------------------------------------

    st.subheader("1. AI Qualification")

    if qualification:
        st.markdown("**Reasoning**")
        st.write(
            qualification.get("reasoning", "Not available.")
        )

        st.markdown("**Qualification recommended next action**")
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

        st.markdown("**Missing information identified during qualification**")

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

    # --------------------------------------------------------
    # 2. AI DECISION AND ROUTING
    # --------------------------------------------------------

    st.subheader("2. AI Decision & Workflow Routing")

    decision = result.get("ai_decision") or {}

    decision_category = (
        result.get("decision_category")
        or decision.get("decision")
        or "Not available"
    )

    decision_reasoning = (
        result.get("decision_reasoning")
        or decision.get("reasoning")
        or "No decision explanation is available."
    )

    decision_next_action = (
        result.get("decision_next_action")
        or decision.get("recommended_next_action")
        or "Manual review recommended."
    )

    decision_route = (
        result.get("decision_route")
        or decision.get("selected_route")
        or "Not available"
    )

    workflow_outcome = (
        result.get("workflow_outcome")
        or decision.get("workflow_outcome")
        or "Not available"
    )

    decision_labels = {
        "prioritize_sales": "Prioritize Sales",
        "request_information": "Request Information",
        "human_review": "Human Review",
        "hold_low_fit": "Hold — Low Fit",
    }

    decision_descriptions = {
        "prioritize_sales": (
            "The lead is eligible to continue to sales-owner assignment."
        ),
        "request_information": (
            "The workflow stopped because additional information "
            "should be collected before sales assignment."
        ),
        "human_review": (
            "The workflow stopped because a person must review "
            "the lead before further processing."
        ),
        "hold_low_fit": (
            "The workflow stopped because the lead was assessed "
            "as low fit for immediate sales prioritization."
        ),
    }

    col1, col2 = st.columns(2)

    col1.metric(
        "AI Decision",
        decision_labels.get(
            decision_category,
            decision_category.replace("_", " ").title(),
        ),
    )

    col2.metric(
        "Selected Route",
        decision_route.replace("_", " ").title(),
    )

    st.markdown("**Why the AI selected this decision**")
    st.write(decision_reasoning)

    st.markdown("**Recommended next action**")
    st.info(decision_next_action)

    if decision_category == "request_information":
        decision_missing = (
            decision.get("missing_information")
            or result.get("missing_information")
            or qualification.get("missing_information")
            or []
        )

        st.markdown("**Information to collect**")

        if decision_missing:
            for item in decision_missing:
                st.write(f"• {item}")
        else:
            st.write(
                "The AI recommends collecting additional information. "
                "Review the decision explanation above for context."
            )

    st.markdown("**Workflow outcome**")
    st.write(
        decision_descriptions.get(
            decision_category,
            workflow_outcome.replace("_", " ").capitalize(),
        )
    )

    st.caption(
        f"Recorded workflow outcome: {workflow_outcome}"
    )

    st.divider()

    # --------------------------------------------------------
    # STOPPED ROUTES
    # --------------------------------------------------------

    if decision_route == "request_information":
        st.warning(
            "Workflow stopped: additional information is needed. "
            "Sales-owner assignment and email-draft generation "
            "were not started."
        )

        st.subheader("3. Final Workflow Status")
        st.info(
            "Waiting for the required lead information before "
            "continuing the sales workflow."
        )

        return

    if decision_route == "human_review":
        st.warning(
            "Workflow stopped: human review is required. "
            "Sales-owner assignment and email-draft generation "
            "were not started."
        )

        st.subheader("3. Final Workflow Status")
        st.info(
            "The lead requires manual review before the workflow "
            "can proceed."
        )

        if result.get("email_warning"):
            st.caption(result["email_warning"])

        return

    if decision_route == "hold_low_fit":
        st.warning(
            "Workflow stopped: this lead has been held as low fit. "
            "Sales-owner assignment and email-draft generation "
            "were not started."
        )

        st.subheader("3. Final Workflow Status")
        st.info(
            "The lead remains recorded in the database, but it was "
            "not sent to automatic sales assignment."
        )

        return

    if decision_route != "prioritize_sales":
        st.warning(
            "The workflow did not receive a recognized decision route. "
            "No automatic sales assignment was started."
        )
        return

    # --------------------------------------------------------
    # 3. SALES OWNER ASSIGNMENT
    # --------------------------------------------------------

    st.subheader("3. Sales Owner Assignment")

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

    # --------------------------------------------------------
    # 4. EMAIL DRAFT
    # --------------------------------------------------------

    st.subheader("4. Follow-up Email Draft")

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

    elif stage == "completed_no_email_consent":
        st.warning(
            result.get(
                "email_warning",
                "Email generation was skipped because contact consent is not recorded.",
            )
        )

    st.divider()

    # --------------------------------------------------------
    # 5. FINAL STATUS
    # --------------------------------------------------------

    st.subheader("5. Final Workflow Status")

    if stage == "workflow_completed":
        st.success("All workflow stages completed.")

    elif stage == "completed_no_email_consent":
        st.success(
            "Lead qualification, decision-making, and assignment "
            "completed. Email generation was skipped because "
            "contact consent was not recorded."
        )

    elif stage == "completed_email_warning":
        st.warning(
            "Lead processing completed, but email draft generation "
            "needs attention."
        )

    elif stage == "owner_assignment_pending":
        st.warning(
            "The lead was prioritized, but no eligible sales owner "
            "was available. It remains in the unassigned queue."
        )

    elif stage == "owner_assignment_warning":
        st.warning(
            "The lead was prioritized, but automatic owner assignment "
            "encountered an issue."
        )

    else:
        st.info(
            f"Workflow stage: {stage}"
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
        "budget": budget_value,
        "timeline": timeline_value,
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

    # --------------------------------------------------------
    # PAGE-LEVEL VALIDATION
    # Required name/email checks are handled by LangGraph.
    # --------------------------------------------------------

    if email.strip() and (
        "@" not in email
        or "." not in email.split("@")[-1]
    ):
        st.error(
            "Please enter a valid email address."
        )

    elif budget == "Custom" and not budget_custom.strip():
        st.error(
            "Please enter a custom budget range."
        )

    elif timeline == "Custom" and not timeline_custom.strip():
        st.error(
            "Please enter a custom expected timeline."
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

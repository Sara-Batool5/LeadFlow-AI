
import json
from datetime import datetime

import streamlit as st

from database import (
    get_email_drafts,
    approve_email_draft,
    get_workflow_events,
    get_leads,
    create_workflow_event,
)


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.title("Human Review & Approval Center")

st.caption(
    "Review uncertain leads, manage information requests, "
    "and approve AI-generated communication."
)

st.divider()


# ============================================================
# HELPERS
# ============================================================

def get_value(record, *keys, default=None):
    """Safely retrieve a value using alternative column names."""

    for key in keys:
        if isinstance(record, dict):
            value = record.get(key)
        else:
            try:
                value = record[key]
            except Exception:
                value = None

        if value is not None:
            return value

    return default


def safe_json(value):
    """Normalize JSON values returned by PostgreSQL."""

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        return {"items": value}

    if isinstance(value, str):
        try:
            parsed = json.loads(value)

            if isinstance(parsed, dict):
                return parsed

            if isinstance(parsed, list):
                return {"items": parsed}

        except Exception:
            pass

    return {}


def normalize_record(record):
    if isinstance(record, dict):
        return record

    try:
        return dict(record)
    except Exception:
        return {}


def format_datetime(value):
    if not value:
        return "Not available"

    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %I:%M %p")

    return str(value)


def normalize_list(value):
    """Convert a database or event value into a readable list."""

    if value is None:
        return []

    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return []

        try:
            parsed = json.loads(value)

            if isinstance(parsed, list):
                return [
                    str(item).strip()
                    for item in parsed
                    if str(item).strip()
                ]

        except Exception:
            pass

        return [value]

    return [str(value)]


def load_records(function):
    result = function()

    if result is None:
        return []

    return [
        normalize_record(item)
        for item in result
        if item is not None
    ]


def event_details(event):
    return safe_json(
        get_value(event, "details", default={})
    )


def event_type(event):
    return str(
        get_value(
            event,
            "event_type",
            default="",
        )
    ).strip().lower()


def get_event_lead_id(event):
    return get_value(
        event,
        "lead_id",
    )


def display_lead_information(lead):
    """Display commonly available lead information."""

    name = get_value(
        lead,
        "contact_name",
        "lead_name",
        default="Unknown contact",
    )

    company = get_value(
        lead,
        "company_name",
        "company",
        default="Unknown company",
    )

    email = get_value(
        lead,
        "email",
        "contact_email",
        default="Not available",
    )

    st.markdown(f"**{name} — {company}**")
    st.caption(f"Email: {email}")


def find_latest_events(events, accepted_types):
    """Return the newest matching event for each lead."""

    latest = {}

    for event in events:

        if event_type(event) not in accepted_types:
            continue

        lead_id = get_event_lead_id(event)

        if lead_id is None:
            continue

        if lead_id not in latest:
            latest[lead_id] = event

    return latest


# ============================================================
# LOAD DATA
# ============================================================

try:
    drafts = load_records(get_email_drafts)
    events = load_records(get_workflow_events)
    leads = load_records(get_leads)

except Exception as exc:
    st.error("Unable to load Human Review Center data.")
    st.exception(exc)
    st.stop()


# ============================================================
# BUILD LEAD LOOKUP
# ============================================================

lead_lookup = {}

for lead in leads:

    lead_id = get_value(
        lead,
        "id",
        "lead_id",
    )

    if lead_id is not None:
        lead_lookup[str(lead_id)] = lead


def get_lead_for_event(event):
    lead_id = get_event_lead_id(event)

    if lead_id is None:
        return {}

    return lead_lookup.get(str(lead_id), {})


# ============================================================
# IDENTIFY DECISION ROUTES
# ============================================================

decision_event_types = {
    "agent_decision_route_selected",
}

qualification_event_types = {
    "agent_ai_qualification_completed",
}

review_action_event_types = {
    "human_review_action_recorded",
}

information_action_event_types = {
    "information_followup_recorded",
}


latest_decisions = find_latest_events(
    events,
    decision_event_types,
)

latest_qualifications = find_latest_events(
    events,
    qualification_event_types,
)

latest_review_actions = find_latest_events(
    events,
    review_action_event_types,
)

latest_information_actions = find_latest_events(
    events,
    information_action_event_types,
)


# ============================================================
# BUILD QUEUES
# ============================================================

human_review_queue = []
information_request_queue = []

for lead_id, decision_event in latest_decisions.items():

    details = event_details(decision_event)

    decision = str(
        details.get(
            "decision",
            details.get("decision_category", ""),
        )
    ).strip().lower()

    selected_route = str(
        details.get(
            "selected_route",
            details.get("decision_route", ""),
        )
    ).strip().lower()

    route = selected_route or decision

    # A lead leaves its active queue as soon as a human action is recorded.
    # The action events are persisted in workflow_events, so this also
    # remains effective after the page is refreshed or reopened.
    if route == "human_review" and lead_id in latest_review_actions:
        continue

    if route == "request_information" and lead_id in latest_information_actions:
        continue

    lead = get_lead_for_event(decision_event)

    qualification_event = latest_qualifications.get(
        lead_id
    )

    qualification_details = (
        event_details(qualification_event)
        if qualification_event
        else {}
    )

    review_action = latest_review_actions.get(
        lead_id
    )

    information_action = latest_information_actions.get(
        lead_id
    )

    review_details = (
        event_details(review_action)
        if review_action
        else {}
    )

    information_details = (
        event_details(information_action)
        if information_action
        else {}
    )

    item = {
        "lead_id": lead_id,
        "lead": lead,
        "decision_event": decision_event,
        "decision_details": details,
        "qualification_details": qualification_details,
        "review_details": review_details,
        "information_details": information_details,
    }

    if route == "human_review":
        human_review_queue.append(item)

    elif route == "request_information":
        information_request_queue.append(item)


# ============================================================
# NORMALIZE EMAIL DRAFT RECORDS
# ============================================================

pending_drafts = []
approved_drafts = []
other_drafts = []

for draft in drafts:

    status = str(
        get_value(
            draft,
            "draft_status",
            "status",
            default="unknown",
        )
    ).strip().lower()

    if status == "pending_review":
        pending_drafts.append(draft)

    elif status == "approved":
        approved_drafts.append(draft)

    else:
        other_drafts.append(draft)


# ============================================================
# TOP SUMMARY
# ============================================================

st.subheader("Review Center Overview")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("[**Human Review Leads ↓**](#human-review-queue)")
    st.metric("Open cases", len(human_review_queue))

with col2:
    st.markdown("[**Information Requests ↓**](#information-request-queue)")
    st.metric("Open cases", len(information_request_queue))

with col3:
    st.markdown("[**Pending Email Drafts ↓**](#pending-email-drafts)")
    st.metric("Awaiting approval", len(pending_drafts))

with col4:
    st.markdown("[**Approved Email Drafts ↓**](#approved-email-drafts)")
    st.metric("Approved", len(approved_drafts))


st.divider()


# ============================================================
# HUMAN REVIEW QUEUE
# ============================================================

st.header("1. Human Review Queue", anchor="human-review-queue")

st.write(
    "Leads routed to human review by the AI Decision Agent. "
    "Review the qualification and record a human decision."
)

if not human_review_queue:

    st.success(
        "There are currently no leads in the Human Review Queue."
    )

else:

    for item in human_review_queue:

        lead_id = item["lead_id"]
        lead = item["lead"]

        decision_details = item["decision_details"]
        qualification = item["qualification_details"]
        review_details = item["review_details"]

        decision = decision_details.get(
            "decision",
            "human_review",
        )

        reasoning = decision_details.get(
            "reasoning",
            decision_details.get(
                "decision_reasoning",
                "No decision reasoning was recorded.",
            ),
        )

        score = qualification.get(
            "score",
            qualification.get(
                "qualification_score",
                "Not available",
            ),
        )

        category = qualification.get(
            "category",
            qualification.get(
                "qualification_category",
                "Not available",
            ),
        )

        next_action = decision_details.get(
            "recommended_next_action",
            decision_details.get(
                "decision_next_action",
                "Review this lead manually.",
            ),
        )

        previous_outcome = review_details.get(
            "review_outcome",
            "",
        )

        previous_notes = review_details.get(
            "reviewer_notes",
            "",
        )

        with st.container(border=True):

            display_lead_information(lead)

            col_a, col_b, col_c = st.columns(3)

            with col_a:
                st.metric(
                    "Lead ID",
                    str(lead_id),
                )

            with col_b:
                st.metric(
                    "Qualification Score",
                    str(score),
                )

            with col_c:
                st.metric(
                    "Qualification",
                    str(category),
                )

            st.markdown("**AI Decision Reasoning**")
            st.write(reasoning)

            st.markdown("**Recommended Next Action**")
            st.write(next_action)

            st.caption(
                "Latest AI decision: "
                + str(decision)
            )

            if previous_outcome:

                st.info(
                    "Previously recorded review outcome: "
                    + str(previous_outcome)
                )

                if previous_notes:
                    st.write(
                        "**Previous reviewer notes:** "
                        + str(previous_notes)
                    )

            with st.expander(
                "View Qualification Details",
                expanded=False,
            ):

                st.write(
                    qualification.get(
                        "reasoning",
                        "No qualification reasoning available.",
                    )
                )

                critical_missing = normalize_list(
                    qualification.get(
                        "critical_missing_information",
                        qualification.get(
                            "missing_information",
                        ),
                    )
                )

                if critical_missing:

                    st.markdown(
                        "**Critical Missing Information**"
                    )

                    for information in critical_missing:
                        st.write(f"- {information}")

            st.markdown("**Record Human Review**")

            review_key = str(lead_id)

            outcome = st.selectbox(
                "Review outcome",
                options=[
                    "Select an outcome",
                    "Approved for Sales",
                    "Request More Information",
                    "Keep on Hold",
                    "Not a Suitable Lead",
                ],
                key=f"human_review_outcome_{review_key}",
            )

            reviewer_notes = st.text_area(
                "Reviewer notes",
                key=f"human_review_notes_{review_key}",
                placeholder=(
                    "Explain your decision or provide "
                    "additional context..."
                ),
            )

            if st.button(
                "Save Review Decision",
                key=f"save_review_{review_key}",
                type="primary",
                use_container_width=True,
            ):

                if outcome == "Select an outcome":

                    st.warning(
                        "Please select a review outcome."
                    )

                elif not reviewer_notes.strip():

                    st.warning(
                        "Please enter reviewer notes before saving."
                    )

                else:

                    try:

                        create_workflow_event(
                            lead_id=int(lead_id),
                            event_type="human_review_action_recorded",
                            message=(
                                "Human review completed. "
                                f"Outcome: {outcome}."
                            ),
                            event_status="completed",
                            details={
                                "review_outcome": outcome,
                                "reviewer_notes": reviewer_notes.strip(),
                                "previous_ai_decision": decision,
                                "qualification_score": score,
                                "qualification_category": category,
                                "review_source": "Human Review Center",
                            },
                            actor="Human Reviewer",
                        )

                        st.success(
                            "Human review decision recorded successfully."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(
                            "Unable to save the human review decision."
                        )

                        st.exception(exc)


# ============================================================
# INFORMATION REQUEST QUEUE
# ============================================================

st.divider()

st.header("2. Information Request Queue", anchor="information-request-queue")

st.write(
    "These leads were routed to request_information because "
    "critical information is required before the workflow "
    "can safely proceed."
)

if not information_request_queue:

    st.success(
        "There are currently no leads awaiting information."
    )

else:

    for item in information_request_queue:

        lead_id = item["lead_id"]
        lead = item["lead"]

        decision_details = item["decision_details"]
        qualification = item["qualification_details"]
        information_details = item["information_details"]

        reasoning = decision_details.get(
            "reasoning",
            decision_details.get(
                "decision_reasoning",
                "No decision reasoning was recorded.",
            ),
        )

        missing_information = normalize_list(
            decision_details.get(
                "missing_information",
                qualification.get(
                    "critical_missing_information",
                    qualification.get(
                        "missing_information",
                        [],
                    ),
                ),
            )
        )

        previous_status = information_details.get(
            "followup_status",
            "",
        )

        previous_notes = information_details.get(
            "followup_notes",
            "",
        )

        with st.container(border=True):

            display_lead_information(lead)

            st.caption(
                f"Lead ID: {lead_id}"
            )

            st.markdown("**Why Information Is Required**")
            st.write(reasoning)

            st.markdown("**Critical Missing Information**")

            if missing_information:

                for information in missing_information:
                    st.write(f"- {information}")

            else:

                st.warning(
                    "The decision event did not contain a "
                    "specific missing-information list. "
                    "Please inspect the lead and add the required details."
                )

            if previous_status:

                st.info(
                    "Latest follow-up status: "
                    + str(previous_status)
                )

                if previous_notes:
                    st.write(
                        "**Previous follow-up notes:** "
                        + str(previous_notes)
                    )

            st.markdown("**Record Information Follow-up**")

            followup_key = str(lead_id)

            followup_status = st.selectbox(
                "Information status",
                options=[
                    "Select status",
                    "Requested",
                    "Partially Received",
                    "Received",
                    "Unable to Obtain",
                ],
                key=f"information_status_{followup_key}",
            )

            followup_notes = st.text_area(
                "Follow-up notes",
                key=f"information_notes_{followup_key}",
                placeholder=(
                    "Record what was requested, received, "
                    "or discussed with the lead..."
                ),
            )

            if st.button(
                "Save Information Follow-up",
                key=f"save_information_{followup_key}",
                type="primary",
                use_container_width=True,
            ):

                if followup_status == "Select status":

                    st.warning(
                        "Please select an information status."
                    )

                elif not followup_notes.strip():

                    st.warning(
                        "Please enter follow-up notes before saving."
                    )

                else:

                    try:

                        create_workflow_event(
                            lead_id=int(lead_id),
                            event_type="information_followup_recorded",
                            message=(
                                "Information follow-up recorded. "
                                f"Status: {followup_status}."
                            ),
                            event_status="completed",
                            details={
                                "followup_status": followup_status,
                                "followup_notes": followup_notes.strip(),
                                "missing_information": missing_information,
                                "followup_source": "Human Review Center",
                            },
                            actor="Human Reviewer",
                        )

                        st.success(
                            "Information follow-up recorded successfully."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(
                            "Unable to save the information follow-up."
                        )

                        st.exception(exc)


# ============================================================
# EMAIL DRAFT REVIEW
# ============================================================

st.divider()

st.header("3. Email Draft Approval")

st.write(
    "Review AI-generated email drafts before treating them "
    "as approved communication."
)

col1, col2, col3 = st.columns(3)

with col1:
    st.metric(
        "Pending Review",
        len(pending_drafts),
    )

with col2:
    st.metric(
        "Approved Drafts",
        len(approved_drafts),
    )

with col3:
    st.metric(
        "Other Drafts",
        len(other_drafts),
    )


# ============================================================
# PENDING EMAIL DRAFTS
# ============================================================

st.subheader("Pending Approval Queue", anchor="pending-email-drafts")

if not pending_drafts:

    st.success(
        "There are currently no email drafts awaiting approval."
    )

else:

    for index, draft in enumerate(pending_drafts):

        draft_id = get_value(
            draft,
            "id",
            "email_draft_id",
            "draft_id",
        )

        lead_id = get_value(
            draft,
            "lead_id",
        )

        recipient = get_value(
            draft,
            "recipient_email",
            "recipient",
            default="Not available",
        )

        subject = get_value(
            draft,
            "subject",
            default="No subject",
        )

        body = get_value(
            draft,
            "body",
            "email_body",
            default="No email body available.",
        )

        created_at = get_value(
            draft,
            "created_at",
            "updated_at",
        )

        with st.container(border=True):

            header_col1, header_col2 = st.columns([4, 1])

            with header_col1:

                st.markdown(f"**{subject}**")

                st.caption(
                    f"Draft ID: {draft_id} | "
                    f"Lead ID: {lead_id if lead_id else 'Not available'}"
                )

            with header_col2:
                st.warning("Pending Review")

            info_col1, info_col2 = st.columns(2)

            with info_col1:
                st.caption("RECIPIENT")
                st.write(recipient)

            with info_col2:
                st.caption("CREATED")
                st.write(format_datetime(created_at))

            st.markdown("**Email Content**")

            st.text_area(
                "Draft body",
                value=str(body),
                height=180,
                disabled=True,
                key=f"review_body_{draft_id}_{index}",
                label_visibility="collapsed",
            )

            if not draft_id:

                st.error(
                    "This draft does not contain a recognizable "
                    "database ID. It cannot be approved here."
                )

            else:

                confirm_approval = st.checkbox(
                    "I have reviewed this email and approve this draft.",
                    key=f"confirm_approval_{draft_id}",
                )

                if st.button(
                    "Approve Draft",
                    key=f"approve_{draft_id}",
                    type="primary",
                    disabled=not confirm_approval,
                    use_container_width=True,
                ):

                    try:

                        approve_email_draft(int(draft_id))

                        st.success(
                            "Draft approved successfully. "
                            "The approval has been recorded."
                        )

                        st.rerun()

                    except Exception as exc:

                        st.error(
                            "The draft could not be approved."
                        )

                        st.exception(exc)

                st.caption(
                    "Approval changes the draft status only. "
                    "It does not send an email."
                )


# ============================================================
# APPROVED EMAIL DRAFTS
# ============================================================

st.subheader("Approved Email Drafts", anchor="approved-email-drafts")

with st.expander(
    f"View Approved Drafts ({len(approved_drafts)})",
    expanded=False,
):

    if not approved_drafts:

        st.info("No drafts have been approved yet.")

    else:

        for draft in approved_drafts:

            draft_id = get_value(
                draft,
                "id",
                "email_draft_id",
                "draft_id",
                default="Not available",
            )

            subject = get_value(
                draft,
                "subject",
                default="No subject",
            )

            recipient = get_value(
                draft,
                "recipient_email",
                "recipient",
                default="Not available",
            )

            body = get_value(
                draft,
                "body",
                "email_body",
                default="No email body available.",
            )

            st.markdown(f"**{subject}**")

            st.caption(
                f"Draft ID: {draft_id} | Recipient: {recipient}"
            )

            st.text(body)

            st.divider()


# ============================================================
# OTHER EMAIL DRAFT STATUSES
# ============================================================

with st.expander(
    f"Other Draft Records ({len(other_drafts)})",
    expanded=False,
):

    if not other_drafts:

        st.info("No other draft records found.")

    else:

        for draft in other_drafts:

            draft_id = get_value(
                draft,
                "id",
                "email_draft_id",
                "draft_id",
                default="Not available",
            )

            subject = get_value(
                draft,
                "subject",
                default="No subject",
            )

            status = get_value(
                draft,
                "draft_status",
                "status",
                default="Unknown",
            )

            st.write(
                f"**{subject}** — {status} "
                f"(Draft ID: {draft_id})"
            )


# ============================================================
# SAFETY NOTICE
# ============================================================

st.divider()

st.info(
    "Human review and information follow-up actions are recorded "
    "in workflow history. Recording a review decision does not "
    "automatically reassign a lead, change its qualification, "
    "or resume the agent workflow. Email approval does not send "
    "an email. No email provider is connected to this page."
)


# ============================================================
# REFRESH
# ============================================================

if st.button(
    "Refresh Review Center",
    use_container_width=False,
):

    st.rerun()

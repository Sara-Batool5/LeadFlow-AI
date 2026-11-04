
import json
import os
import re
from typing import TypedDict, Any

import streamlit as st
from groq import Groq
from langgraph.graph import StateGraph, END

from database import (
    find_potential_duplicates,
    create_lead,
    get_lead_by_id,
    save_qualification_result,
    update_lead_qualification,
    create_workflow_event,
    assign_lead_automatically,
    save_email_draft,
)


# ============================================================
# WORKFLOW STATE
# ============================================================

class LeadWorkflowState(TypedDict, total=False):
    lead_data: dict
    allow_duplicate: bool
    duplicate_matches: list

    lead_id: int
    lead: dict
    lead_reference: str

    qualification: dict

    assignment_success: bool
    assignment_message: str
    assigned_owner: dict

    draft_id: int
    email_subject: str
    email_body: str

    stage: str
    route: str
    error: str
    email_warning: str


# ============================================================
# CONFIGURATION
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
        raise ValueError(
            "GROQ_API_KEY is missing from Streamlit Cloud secrets."
        )

    return Groq(api_key=api_key)


def get_groq_model():
    return get_secret(
        "GROQ_MODEL",
        "openai/gpt-oss-120b",
    )


def clean_json_response(content):
    content = (content or "").strip()
    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


# ============================================================
# AGENT 1 — INTAKE VALIDATION
# ============================================================

def intake_validation_agent(state: LeadWorkflowState):
    lead = dict(state.get("lead_data") or {})

    contact_name = str(
        lead.get("contact_name")
        or lead.get("full_name")
        or ""
    ).strip()

    email = str(lead.get("email") or "").strip()

    if not contact_name:
        return {
            "stage": "validation_failed",
            "route": "error",
            "error": "Contact name is required.",
        }

    if not email or "@" not in email:
        return {
            "stage": "validation_failed",
            "route": "error",
            "error": "A valid email address is required.",
        }

    domain = email.split("@")[-1]

    if "." not in domain:
        return {
            "stage": "validation_failed",
            "route": "error",
            "error": "Please provide a valid email address.",
        }

    lead["contact_name"] = contact_name
    lead["description"] = (
        lead.get("description")
        or lead.get("need_description")
        or "Not provided"
    )

    lead["consent_to_contact"] = bool(
        lead.get("consent_to_contact", False)
    )

    return {
        "lead_data": lead,
        "stage": "intake_validated",
        "route": "continue",
    }


# ============================================================
# AGENT 2 — DUPLICATE DETECTION
# ============================================================

def duplicate_detection_agent(state: LeadWorkflowState):
    lead_data = state["lead_data"]

    matches = find_potential_duplicates(lead_data)

    if matches and not state.get("allow_duplicate", False):
        return {
            "duplicate_matches": matches,
            "stage": "duplicate_review_required",
            "route": "duplicate_review",
        }

    return {
        "duplicate_matches": matches or [],
        "stage": "duplicate_check_passed",
        "route": "continue",
    }


# ============================================================
# AGENT 3 — LEAD CREATION
# ============================================================

def lead_creation_agent(state: LeadWorkflowState):
    try:
        created = create_lead(state["lead_data"])

        lead_id = created["id"]
        lead_reference = created.get("lead_reference")

        create_workflow_event(
            lead_id,
            "agent_workflow_lead_created",
            "Lead created through the LangGraph autonomous workflow.",
            details={
                "lead_reference": lead_reference,
                "workflow": "LeadFlow AI Step 8",
            },
        )

        return {
            "lead_id": lead_id,
            "lead_reference": lead_reference,
            "stage": "lead_created",
            "route": "continue",
        }

    except Exception as exc:
        return {
            "stage": "lead_creation_failed",
            "route": "error",
            "error": str(exc),
        }


# ============================================================
# AGENT 4 — AI LEAD QUALIFICATION
# ============================================================

def qualification_agent(state: LeadWorkflowState):
    try:
        lead = get_lead_by_id(state["lead_id"])

        if not lead:
            raise ValueError("The newly created lead could not be retrieved.")

        client = get_groq_client()

        prompt = f"""
You are an experienced B2B sales qualification analyst.

Evaluate the lead using only the supplied information.
Do not invent facts or assume information that is not provided.

LEAD INFORMATION
Contact: {lead.get('contact_name')}
Email: {lead.get('email')}
Company: {lead.get('company')}
Job title: {lead.get('job_title')}
Industry: {lead.get('industry')}
Company size: {lead.get('company_size')}
Country: {lead.get('country')}
Website: {lead.get('website')}
Budget: {lead.get('budget')}
Timeline: {lead.get('timeline')}
Business need: {lead.get('description')}

Return valid JSON only using this structure:
{{
    "score": 0,
    "category": "High | Medium | Low | Needs Review",
    "reasoning": "Short explanation",
    "missing_information": ["item 1"],
    "recommended_next_action": "Specific next action",
    "human_review_required": true
}}

SCORING
80-100: High potential
50-79: Medium potential
0-49: Low potential

Use Needs Review if essential information is insufficient.
Do not inflate the score.
"""

        response = client.chat.completions.create(
            model=get_groq_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful B2B lead qualification "
                        "assistant. Return valid JSON only."
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

        content = clean_json_response(
            response.choices[0].message.content
        )

        result = json.loads(content)

        score = max(
            0,
            min(100, int(result.get("score", 0))),
        )

        result["score"] = score

        missing = result.get("missing_information", [])

        if not isinstance(missing, list):
            result["missing_information"] = [str(missing)]

        result.setdefault("category", "Needs Review")
        result.setdefault("reasoning", "No reasoning was returned.")
        result.setdefault(
            "recommended_next_action",
            "Review the lead manually.",
        )
        result.setdefault("human_review_required", True)

        save_qualification_result(
            state["lead_id"],
            result,
            model_name=get_groq_model(),
        )

        update_lead_qualification(
            state["lead_id"],
            score,
            result["category"],
        )

        create_workflow_event(
            state["lead_id"],
            "agent_ai_qualification_completed",
            "LangGraph qualification agent completed its assessment.",
            details=result,
        )

        return {
            "lead": lead,
            "qualification": result,
            "stage": "qualification_completed",
            "route": "continue",
        }

    except Exception as exc:
        return {
            "stage": "qualification_failed",
            "route": "error",
            "error": str(exc),
        }


# ============================================================
# AGENT 5 — INTELLIGENT SALES OWNER ASSIGNMENT
# ============================================================

def owner_assignment_agent(state: LeadWorkflowState):
    try:
        success, message, owner = assign_lead_automatically(
            state["lead_id"]
        )

        if success:
            return {
                "assignment_success": True,
                "assignment_message": message,
                "assigned_owner": owner,
                "stage": "owner_assigned",
                "route": "continue",
            }

        create_workflow_event(
            state["lead_id"],
            "agent_assignment_unavailable",
            message,
            details={
                "assignment_success": False,
            },
        )

        return {
            "assignment_success": False,
            "assignment_message": message,
            "assigned_owner": {},
            "stage": "owner_assignment_pending",
            "route": "continue",
        }

    except Exception as exc:
        return {
            "assignment_success": False,
            "assignment_message": (
                f"Automatic assignment could not be completed: {exc}"
            ),
            "assigned_owner": {},
            "stage": "owner_assignment_warning",
            "route": "continue",
        }


# ============================================================
# AGENT 6 — AI FOLLOW-UP EMAIL DRAFT
# ============================================================

def email_draft_agent(state: LeadWorkflowState):
    lead = get_lead_by_id(state["lead_id"])

    if not lead:
        return {
            "stage": "email_draft_failed",
            "email_warning": "Lead could not be retrieved for email generation.",
            "route": "complete",
        }

    if not lead.get("consent_to_contact"):
        create_workflow_event(
            state["lead_id"],
            "agent_email_skipped_no_consent",
            (
                "Email draft generation was skipped because "
                "contact consent is not recorded."
            ),
            details={
                "draft_created": False,
                "reason": "consent_not_recorded",
            },
        )

        return {
            "stage": "completed_no_email_consent",
            "email_warning": (
                "No email draft was generated because contact consent "
                "is not recorded for this lead."
            ),
            "route": "complete",
        }

    try:
        client = get_groq_client()

        qualification = state.get("qualification") or {}

        owner_name = (
            lead.get("assigned_owner")
            or "the sales team"
        )

        prompt = f"""
You are a professional B2B sales communication specialist.

Create a personalized first follow-up email for this lead.

LEAD
Contact: {lead.get('contact_name') or 'there'}
Company: {lead.get('company') or 'their organization'}
Job title: {lead.get('job_title') or 'Not provided'}
Industry: {lead.get('industry') or 'Not provided'}
Website: {lead.get('website') or 'Not provided'}
Business need: {lead.get('description') or 'Not provided'}
Budget: {lead.get('budget') or 'Not provided'}
Timeline: {lead.get('timeline') or 'Not provided'}
Assigned owner: {owner_name}

QUALIFICATION
Score: {qualification.get('score', 'Not available')}
Category: {qualification.get('category', 'Not available')}
Reasoning: {qualification.get('reasoning', 'Not available')}
Recommended next action:
{qualification.get('recommended_next_action', 'Review the lead.')}

EMAIL PURPOSE
Initial personalized follow-up after receiving an inquiry.

TONE
Professional and friendly.

RULES
1. Do not invent company facts, services, prices, or promises.
2. Do not claim that a meeting or call has already happened.
3. Do not invent a sender's name or job title.
4. Keep the email concise, usually 100-180 words.
5. Include a polite and clear next step.
6. Use only the supplied lead information.
7. Return only this format:

SUBJECT: [subject]

BODY:
[email body]
"""

        response = client.chat.completions.create(
            model=get_groq_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write accurate, personalized, professional "
                        "B2B sales emails."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.4,
            max_tokens=900,
        )

        output = (
            response.choices[0].message.content or ""
        ).strip()

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

        subject = (
            subject_match.group(1).strip()
            if subject_match
            else "Follow-up regarding your inquiry"
        )

        body = (
            body_match.group(1).strip()
            if body_match
            else output
        )

        if not subject or not body:
            raise ValueError(
                "The AI did not return a complete email draft."
            )

        draft_id = save_email_draft(
            state["lead_id"],
            lead.get("email"),
            subject,
            body,
        )

        create_workflow_event(
            state["lead_id"],
            "agent_email_draft_created",
            "LangGraph created a follow-up email draft for human review.",
            details={
                "email_draft_id": draft_id,
                "subject": subject,
                "approval_required": True,
                "email_sent": False,
            },
        )

        return {
            "draft_id": draft_id,
            "email_subject": subject,
            "email_body": body,
            "stage": "workflow_completed",
            "route": "complete",
        }

    except Exception as exc:
        return {
            "stage": "completed_email_warning",
            "email_warning": str(exc),
            "route": "complete",
        }


# ============================================================
# ROUTING FUNCTIONS
# ============================================================

def route_validation(state):
    return state.get("route", "continue")


def route_duplicates(state):
    return state.get("route", "continue")


def route_creation(state):
    return state.get("route", "continue")


def route_qualification(state):
    return state.get("route", "continue")


# ============================================================
# LANGGRAPH CONSTRUCTION
# ============================================================

def build_lead_workflow():
    graph = StateGraph(LeadWorkflowState)

    graph.add_node(
        "intake_validation",
        intake_validation_agent,
    )

    graph.add_node(
        "duplicate_detection",
        duplicate_detection_agent,
    )

    graph.add_node(
        "lead_creation",
        lead_creation_agent,
    )

    graph.add_node(
        "qualification",
        qualification_agent,
    )

    graph.add_node(
        "owner_assignment",
        owner_assignment_agent,
    )

    graph.add_node(
        "email_draft",
        email_draft_agent,
    )

    graph.set_entry_point("intake_validation")

    graph.add_conditional_edges(
        "intake_validation",
        route_validation,
        {
            "continue": "duplicate_detection",
            "error": END,
        },
    )

    graph.add_conditional_edges(
        "duplicate_detection",
        route_duplicates,
        {
            "continue": "lead_creation",
            "duplicate_review": END,
        },
    )

    graph.add_conditional_edges(
        "lead_creation",
        route_creation,
        {
            "continue": "qualification",
            "error": END,
        },
    )

    graph.add_conditional_edges(
        "qualification",
        route_qualification,
        {
            "continue": "owner_assignment",
            "error": END,
        },
    )

    graph.add_edge(
        "owner_assignment",
        "email_draft",
    )

    graph.add_edge(
        "email_draft",
        END,
    )

    return graph.compile()


# ============================================================
# PUBLIC WORKFLOW FUNCTION
# ============================================================

def run_lead_workflow(lead_data, allow_duplicate=False):
    """
    Execute the complete LangGraph lead workflow.

    When a possible duplicate is found, the workflow stops before
    creating a record. The caller may request a second run with
    allow_duplicate=True after reviewing the matches.
    """

    graph = build_lead_workflow()

    initial_state = {
        "lead_data": dict(lead_data),
        "allow_duplicate": bool(allow_duplicate),
        "duplicate_matches": [],
        "stage": "started",
        "route": "continue",
    }

    return graph.invoke(initial_state)

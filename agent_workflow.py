
import json
import os
import re
from typing import TypedDict

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

    # Phase 11 — AI Decision Agent
    ai_decision: dict
    decision_category: str
    decision_reasoning: str
    decision_next_action: str
    decision_route: str
    workflow_outcome: str
    missing_information: list

    stage: str
    route: str
    error: str
    email_warning: str


# ============================================================
# CONFIGURATION
# ============================================================

ALLOWED_QUALIFICATION_CATEGORIES = {
    "high_fit",
    "medium_fit",
    "low_fit",
    "needs_review",
}

ALLOWED_PRIORITIES = {
    "unassessed",
    "low",
    "medium",
    "high",
    "urgent",
}

ALLOWED_DECISION_CATEGORIES = {
    "prioritize_sales",
    "request_information",
    "human_review",
    "hold_low_fit",
}


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


def normalize_qualification_category(category, score=None):
    original = str(category or "").strip().lower()

    normalized = re.sub(r"[\s\-]+", "_", original)
    normalized = re.sub(r"[^a-z_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    aliases = {
        "high": "high_fit",
        "highfit": "high_fit",
        "high_potential": "high_fit",
        "high_fit": "high_fit",
        "medium": "medium_fit",
        "mediumfit": "medium_fit",
        "medium_potential": "medium_fit",
        "medium_fit": "medium_fit",
        "low": "low_fit",
        "lowfit": "low_fit",
        "low_potential": "low_fit",
        "low_fit": "low_fit",
        "needsreview": "needs_review",
        "need_review": "needs_review",
        "needs_review": "needs_review",
        "review": "needs_review",
        "manual_review": "needs_review",
    }

    result = aliases.get(normalized)

    if result not in ALLOWED_QUALIFICATION_CATEGORIES:
        if score is None:
            result = "needs_review"
        elif score >= 80:
            result = "high_fit"
        elif score >= 50:
            result = "medium_fit"
        else:
            result = "low_fit"

    if result not in ALLOWED_QUALIFICATION_CATEGORIES:
        result = "needs_review"

    return result


def normalize_lead_priority(priority):
    original = str(priority or "unassessed").strip().lower()

    mapping = {
        "high_fit": "high",
        "medium_fit": "medium",
        "low_fit": "low",
        "needs_review": "unassessed",
    }

    normalized = mapping.get(original, original)

    if normalized not in ALLOWED_PRIORITIES:
        normalized = "unassessed"

    return normalized


def parse_email_response(output):
    output = (output or "").strip()

    output = re.sub(
        r"^```(?:text|markdown|email)?\s*",
        "",
        output,
        flags=re.IGNORECASE,
    )

    output = re.sub(r"\s*```$", "", output).strip()

    if not output:
        raise ValueError(
            "The AI returned an empty email response."
        )

    subject_match = re.search(
        r"^\s*(?:SUBJECT(?:\s+LINE)?|EMAIL SUBJECT)\s*:\s*(.+?)\s*$",
        output,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    subject = (
        subject_match.group(1).strip()
        if subject_match
        else ""
    )

    body_match = re.search(
        r"^\s*(?:BODY|EMAIL BODY)\s*:\s*(.*)$",
        output,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )

    body = (
        body_match.group(1).strip()
        if body_match
        else ""
    )

    if not subject:
        heading_subject = re.search(
            r"^\s*#{1,3}\s*(?:SUBJECT|SUBJECT LINE)\s*:?\s*(.+?)\s*$",
            output,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        if heading_subject:
            subject = heading_subject.group(1).strip()

    if not body:
        heading_body = re.search(
            r"^\s*#{1,3}\s*(?:BODY|EMAIL BODY)\s*:?\s*(.*)$",
            output,
            flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
        )

        if heading_body:
            body = heading_body.group(1).strip()

    if not subject and not body:
        lines = output.splitlines()

        if len(lines) >= 2:
            subject = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

    subject = re.sub(r"^#+\s*", "", subject).strip()
    body = re.sub(r"^#+\s*", "", body).strip()

    body = re.sub(
        r"^(?:BODY|EMAIL BODY)\s*:\s*",
        "",
        body,
        flags=re.IGNORECASE,
    ).strip()

    if not subject or not body:
        raise ValueError(
            "The AI did not return a complete email draft. "
            "Please retry email draft generation."
        )

    if len(subject) > 250:
        raise ValueError(
            "The generated email subject is unexpectedly long."
        )

    return subject, body


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

    lead["priority"] = normalize_lead_priority(
        lead.get("priority")
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
            raise ValueError(
                "The newly created lead could not be retrieved."
            )

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

Return valid JSON only:

{{
    "score": 0,
    "category": "needs_review",
    "reasoning": "Short explanation",
    "missing_information": [],
    "recommended_next_action": "Specific next action",
    "human_review_required": true
}}

CATEGORY VALUES:
high_fit
medium_fit
low_fit
needs_review

SCORING:
80-100: high_fit
50-79: medium_fit
0-49: low_fit

Use needs_review if essential information is insufficient.
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

        original_category = result.get("category", "")

        normalized_category = normalize_qualification_category(
            original_category,
            score,
        )

        result["category"] = normalized_category

        if str(original_category).strip().lower() != normalized_category:
            result["original_ai_category"] = str(original_category)

        missing = result.get("missing_information", [])

        if not isinstance(missing, list):
            missing = [str(missing)]

        result["missing_information"] = [
            str(item).strip()
            for item in missing
            if str(item).strip()
        ]

        result.setdefault(
            "reasoning",
            "No reasoning was returned.",
        )

        result.setdefault(
            "recommended_next_action",
            "Review the lead manually.",
        )

        result["human_review_required"] = bool(
            result.get("human_review_required", True)
        )

        if normalized_category == "needs_review":
            result["human_review_required"] = True

        if result["category"] not in ALLOWED_QUALIFICATION_CATEGORIES:
            raise ValueError(
                "Invalid qualification category generated."
            )

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
# AGENT 5 — AI DECISION AGENT (PHASE 11.1 + 11.2)
# ============================================================

def ai_decision_agent(state: LeadWorkflowState):
    """
    Evaluate qualification results and determine the next workflow route.

    Safe routing rules:
    - Human review takes precedence when explicitly required.
    - needs_review qualification always goes to human review.
    - Missing information routes to request_information.
    - low_fit qualification routes to hold_low_fit.
    - Only suitable high_fit or medium_fit leads can proceed
      to sales-owner assignment.
    - Any decision-agent failure routes to human review.
    """

    lead_id = state.get("lead_id")
    lead = state.get("lead") or {}
    qualification = state.get("qualification") or {}

    try:
        if not qualification:
            raise ValueError(
                "Qualification results are unavailable for decision-making."
            )

        score = qualification.get("score", 0)
        category = str(
            qualification.get("category", "needs_review")
        ).strip().lower()

        missing_information = qualification.get(
            "missing_information",
            [],
        )

        if not isinstance(missing_information, list):
            missing_information = [str(missing_information)]

        missing_information = [
            str(item).strip()
            for item in missing_information
            if str(item).strip()
        ]

        human_review_required = bool(
            qualification.get("human_review_required", True)
        )

        client = get_groq_client()

        prompt = f"""
You are the AI Decision Agent for LeadFlow AI,
a B2B lead-management and sales workflow system.

Recommend exactly one next action using only the supplied data.

LEAD
Contact: {lead.get('contact_name', 'Not provided')}
Company: {lead.get('company', 'Not provided')}
Job title: {lead.get('job_title', 'Not provided')}
Industry: {lead.get('industry', 'Not provided')}
Company size: {lead.get('company_size', 'Not provided')}
Country: {lead.get('country', 'Not provided')}
Budget: {lead.get('budget', 'Not provided')}
Timeline: {lead.get('timeline', 'Not provided')}
Business need: {lead.get('description', 'Not provided')}

QUALIFICATION
Score: {score}
Category: {category}
Reasoning: {qualification.get('reasoning', 'Not provided')}
Missing information: {json.dumps(missing_information)}
Qualification next action:
{qualification.get('recommended_next_action', 'Not provided')}
Human review required: {human_review_required}

Allowed decision values:
prioritize_sales
request_information
human_review
hold_low_fit

Rules:
- Choose human_review if human review is required or the category is needs_review.
- Choose request_information if important information is missing.
- Choose hold_low_fit if the qualification category is low_fit.
- Choose prioritize_sales only when the category is high_fit or medium_fit,
  no essential information is missing, and human review is not required.
- Do not change the qualification score or category.
- Do not claim that an email has been sent or information has been requested.
- You are recommending an action only.

Return valid JSON only:

{{
    "decision": "prioritize_sales",
    "reasoning": "Explain the decision.",
    "recommended_next_action": "Describe the next step."
}}
"""

        response = client.chat.completions.create(
            model=get_groq_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a cautious B2B sales decision agent. "
                        "Return valid JSON only and select one allowed "
                        "decision category."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.1,
            max_tokens=700,
        )

        content = clean_json_response(
            response.choices[0].message.content
        )

        result = json.loads(content)

        decision = str(
            result.get("decision", "")
        ).strip().lower()

        if decision not in ALLOWED_DECISION_CATEGORIES:
            raise ValueError(
                "The AI returned an unsupported decision category."
            )

        reasoning = str(
            result.get("reasoning") or ""
        ).strip()

        recommended_next_action = str(
            result.get("recommended_next_action") or ""
        ).strip()

        if not reasoning or not recommended_next_action:
            raise ValueError(
                "The AI decision is missing its explanation or next action."
            )

        # ----------------------------------------------------
        # DETERMINISTIC SAFETY OVERRIDES
        # ----------------------------------------------------

        if human_review_required or category == "needs_review":
            decision = "human_review"

            reasoning = (
                "Human review is required by the qualification result. "
                + reasoning
            )

            recommended_next_action = (
                "A team member must review the lead and qualification "
                "before any sales assignment. "
                + recommended_next_action
            )

        elif missing_information:
            decision = "request_information"

            reasoning = (
                "The qualification identified missing information. "
                + reasoning
            )

            recommended_next_action = (
                "Collect the missing information before sales assignment: "
                + "; ".join(missing_information)
            )

        elif category == "low_fit":
            decision = "hold_low_fit"

            reasoning = (
                "The qualification category is low_fit. "
                + reasoning
            )

            recommended_next_action = (
                "Keep the lead out of immediate sales prioritization "
                "and review it later if new information becomes available."
            )

        elif category not in {"high_fit", "medium_fit"}:
            decision = "human_review"

            reasoning = (
                "The qualification category is not eligible for automatic "
                "sales prioritization. " + reasoning
            )

            recommended_next_action = (
                "Review the qualification and lead details manually."
            )

        elif decision == "prioritize_sales":
            # This is the only decision that can continue automatically.
            pass

        elif decision == "request_information":
            # The AI can request additional information even if the
            # qualification did not list a specific missing field.
            pass

        elif decision == "hold_low_fit":
            # Do not let the AI hold a medium/high-fit lead as low-fit.
            decision = "human_review"
            reasoning = (
                "The AI proposed a low-fit hold, but the qualification "
                "category is not low_fit. Manual review is required. "
                + reasoning
            )
            recommended_next_action = (
                "Review the mismatch between the AI decision and "
                "qualification category."
            )

        elif decision == "human_review":
            pass

        # ----------------------------------------------------
        # DETERMINE WORKFLOW ROUTE
        # ----------------------------------------------------

        if decision == "prioritize_sales":
            decision_route = "prioritize_sales"
            workflow_outcome = "continuing_to_owner_assignment"
            final_stage = "decision_prioritize_sales"

        elif decision == "request_information":
            decision_route = "request_information"
            workflow_outcome = "stopped_pending_information"
            final_stage = "workflow_stopped_for_information"

        elif decision == "hold_low_fit":
            decision_route = "hold_low_fit"
            workflow_outcome = "held_low_fit"
            final_stage = "workflow_held_low_fit"

        else:
            decision = "human_review"
            decision_route = "human_review"
            workflow_outcome = "stopped_for_human_review"
            final_stage = "workflow_stopped_for_human_review"

        decision_result = {
            "decision": decision,
            "reasoning": reasoning,
            "recommended_next_action": recommended_next_action,
            "human_review_required": decision == "human_review",
            "qualification_score": score,
            "qualification_category": category,
            "missing_information": missing_information,
            "selected_route": decision_route,
            "workflow_outcome": workflow_outcome,
        }

        # Record the AI's final decision.
        create_workflow_event(
            lead_id,
            "agent_ai_decision_completed",
            "AI Decision Agent evaluated the qualification results.",
            details=decision_result,
        )

        # Record the actual route selected by the workflow.
        create_workflow_event(
            lead_id,
            "agent_decision_route_selected",
            (
                f"Decision route selected: {decision_route}. "
                f"Workflow outcome: {workflow_outcome}."
            ),
            details=decision_result,
        )

        return {
            "ai_decision": decision_result,
            "decision_category": decision,
            "decision_reasoning": reasoning,
            "decision_next_action": recommended_next_action,
            "decision_route": decision_route,
            "workflow_outcome": workflow_outcome,
            "missing_information": missing_information,
            "stage": final_stage,
            "route": decision_route,
        }

    except Exception as exc:
        # A failed or uncertain decision must never continue
        # automatically to owner assignment.
        fallback_decision = {
            "decision": "human_review",
            "reasoning": (
                "The AI Decision Agent could not complete a reliable "
                "assessment. Manual review is required."
            ),
            "recommended_next_action": (
                "Review the qualification results and lead information "
                "manually before proceeding."
            ),
            "human_review_required": True,
            "qualification_score": qualification.get("score"),
            "qualification_category": qualification.get("category"),
            "selected_route": "human_review",
            "workflow_outcome": "stopped_for_human_review",
            "decision_error": str(exc),
        }

        try:
            create_workflow_event(
                lead_id,
                "agent_ai_decision_fallback",
                "AI Decision Agent used the safe human-review fallback.",
                details=fallback_decision,
            )

            create_workflow_event(
                lead_id,
                "agent_decision_route_selected",
                "Decision route selected: human_review after decision-agent fallback.",
                details=fallback_decision,
            )
        except Exception:
            pass

        return {
            "ai_decision": fallback_decision,
            "decision_category": "human_review",
            "decision_reasoning": fallback_decision["reasoning"],
            "decision_next_action": fallback_decision[
                "recommended_next_action"
            ],
            "decision_route": "human_review",
            "workflow_outcome": "stopped_for_human_review",
            "missing_information": qualification.get(
                "missing_information",
                [],
            ),
            "stage": "workflow_stopped_for_human_review",
            "route": "human_review",
            "email_warning": (
                "The decision agent encountered an issue. "
                "The workflow safely stopped for human review."
            ),
        }


# ============================================================
# AGENT 6 — INTELLIGENT SALES OWNER ASSIGNMENT
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
            details={"assignment_success": False},
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
# AGENT 7 — AI FOLLOW-UP EMAIL DRAFT
# ============================================================

def email_draft_agent(state: LeadWorkflowState):
    lead = get_lead_by_id(state["lead_id"])

    if not lead:
        return {
            "stage": "email_draft_failed",
            "email_warning": (
                "Lead could not be retrieved for email generation."
            ),
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

Write a concise, professional, personalized email of approximately
100-180 words.

Do not invent facts, prices, promises, sender names, or meetings.
Include a polite next step.
Do not claim that the company has already reviewed or approved anything.

STRICT OUTPUT FORMAT:

SUBJECT: Write the email subject here

BODY:
Write the complete email body here.

Do not add Markdown headings, code fences, explanations,
or any text outside this exact format.
"""

        response = client.chat.completions.create(
            model=get_groq_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write accurate, personalized, professional "
                        "B2B sales emails. Always return both a subject "
                        "and a complete body using the exact requested "
                        "format. Never omit either field."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        output = (
            response.choices[0].message.content or ""
        ).strip()

        subject, body = parse_email_response(output)

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
            "email_warning": (
                f"Email draft generation failed: {exc}"
            ),
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


def route_decision(state):
    """
    Only prioritize_sales may continue to owner assignment.
    All other decisions terminate the workflow.
    """

    decision_route = state.get("decision_route")

    if decision_route == "prioritize_sales":
        return "prioritize_sales"

    if decision_route in {
        "request_information",
        "human_review",
        "hold_low_fit",
    }:
        return decision_route

    # Unknown or missing route is treated as human review.
    return "human_review"


# ============================================================
# LANGGRAPH CONSTRUCTION
# ============================================================

def build_lead_workflow():
    graph = StateGraph(LeadWorkflowState)

    graph.add_node("intake_validation", intake_validation_agent)
    graph.add_node("duplicate_detection", duplicate_detection_agent)
    graph.add_node("lead_creation", lead_creation_agent)
    graph.add_node("qualification", qualification_agent)
    graph.add_node("ai_decision", ai_decision_agent)
    graph.add_node("owner_assignment", owner_assignment_agent)
    graph.add_node("email_draft", email_draft_agent)

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
            "continue": "ai_decision",
            "error": END,
        },
    )

    # Phase 11.2: Decision-based conditional routing.
    graph.add_conditional_edges(
        "ai_decision",
        route_decision,
        {
            "prioritize_sales": "owner_assignment",
            "request_information": END,
            "human_review": END,
            "hold_low_fit": END,
        },
    )

    graph.add_edge("owner_assignment", "email_draft")
    graph.add_edge("email_draft", END)

    return graph.compile()


# ============================================================
# PUBLIC WORKFLOW FUNCTION
# ============================================================

def run_lead_workflow(lead_data, allow_duplicate=False):
    """
    Execute the complete LangGraph lead workflow.
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

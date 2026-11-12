
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
    record_agent_outcome,
    get_relevant_agent_memories,
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

    # Phase 12.2 — Agent Memory Retrieval
    agent_memories: list
    memory_retrieval_status: str
    memory_retrieval_count: int

    stage: str
    route: str
    error: str
    email_warning: str
    
    # Phase 13.1 — Workflow Failure Detection
    failure_detected: bool
    failure_stage: str
    failure_classification: str
    underlying_failure_classification: str
    failure_message: str
    failure_exception_type: str
    failure_error_code: str
    failure_retryable: bool
    lead_created_before_failure: bool

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


# ============================================================
# PHASE 13.1 — WORKFLOW FAILURE CLASSIFICATION
# ============================================================

def classify_workflow_failure(
    exc,
    stage,
    lead_created=False,
):
    """
    Classify a workflow exception without performing retries.

    Categories:
    - validation_failure
    - permanent_failure
    - transient_failure
    - partial_failure
    - unknown_failure

    A failure after successful lead creation is classified
    as partial_failure. Its underlying technical cause is
    preserved separately.
    """

    error_message = str(exc or "Unknown workflow error")
    exception_type = type(exc).__name__

    error_code = str(
        getattr(exc, "pgcode", None)
        or getattr(exc, "code", None)
        or ""
    )

    stage_name = str(stage or "unknown").strip().lower()

    exception_name = exception_type.lower()
    error_text = error_message.lower()

    # --------------------------------------------------------
    # DETERMINE THE UNDERLYING FAILURE
    # --------------------------------------------------------

    if stage_name in {
        "intake_validation",
        "validation",
    }:
        underlying_classification = "validation_failure"
        retryable = False

    elif (
        exception_name in {
            "integrityerror",
            "programmingerror",
            "dataerror",
            "notnullviolation",
            "uniqueviolation",
            "checkviolation",
            "foreignkeyviolation",
        }
        or error_code.startswith("23")
        or error_code.startswith("42")
    ):
        underlying_classification = "permanent_failure"
        retryable = False

    elif (
        exception_name in {
            "operationalerror",
            "interfaceerror",
            "timeouterror",
            "timeout",
            "ratelimiterror",
            "apiconnectionerror",
            "apitimeouterror",
            "serviceunavailableerror",
        }
        or "timeout" in error_text
        or "temporarily unavailable" in error_text
        or "connection reset" in error_text
        or "connection refused" in error_text
        or "rate limit" in error_text
        or "rate_limit" in error_text
        or "too many requests" in error_text
        or "service unavailable" in error_text
    ):
        underlying_classification = "transient_failure"
        retryable = True

    elif isinstance(exc, ValueError):
        underlying_classification = "permanent_failure"
        retryable = False

    else:
        underlying_classification = "unknown_failure"
        retryable = False

    # --------------------------------------------------------
    # DETERMINE THE OVERALL WORKFLOW FAILURE
    # --------------------------------------------------------

    if lead_created and stage_name != "lead_creation":
        classification = "partial_failure"

    else:
        classification = underlying_classification

    return {
        "failure_detected": True,
        "failure_stage": stage_name,
        "failure_classification": classification,
        "underlying_failure_classification": (
            underlying_classification
        ),
        "failure_message": error_message,
        "failure_exception_type": exception_type,
        "failure_error_code": error_code,
        "failure_retryable": retryable,
        "lead_created_before_failure": bool(lead_created),
    }


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
# PHASE 12.1 — STANDARDIZED OUTCOME RECORDING
# ============================================================

def record_workflow_outcome_safely(
    state,
    outcome,
    message,
    additional_details=None,
):
    """
    Record a standardized workflow outcome using the existing
    workflow_events table.

    An outcome-recording error must not interrupt the main
    lead workflow.
    """

    lead_id = state.get("lead_id")

    if not lead_id:
        return False

    qualification = state.get("qualification") or {}
    decision = state.get("ai_decision") or {}
    owner = state.get("assigned_owner") or {}

    details = {
        "workflow_stage": state.get("stage"),
        "decision_category": state.get("decision_category"),
        "decision_route": state.get("decision_route"),
        "workflow_outcome": state.get("workflow_outcome"),
        "qualification_score": qualification.get("score"),
        "qualification_category": qualification.get("category"),
        "assignment_success": state.get("assignment_success"),
        "assignment_message": state.get("assignment_message"),
        "assigned_owner": owner,
        "draft_id": state.get("draft_id"),
        "email_sent": False,
        "approval_required": True,
        "decision": decision,
    }

    if additional_details:
        details.update(additional_details)

    try:
        record_agent_outcome(
            lead_id=lead_id,
            outcome=outcome,
            details=details,
            message=message,
        )

        return True

    except Exception:
        # Outcome recording must never interrupt the main workflow.
        return False


# ============================================================
# AGENT 1 — INTAKE VALIDATION
# ============================================================

def intake_validation_agent(state: LeadWorkflowState):
    lead = dict(state.get("lead_data") or {})

    def validation_failure(message):
        failure = classify_workflow_failure(
            ValueError(message),
            stage="intake_validation",
            lead_created=bool(state.get("lead_id")),
        )

        return {
            **failure,
            "stage": "validation_failed",
            "route": "error",
            "error": message,
        }

    try:
        contact_name = str(
            lead.get("contact_name")
            or lead.get("full_name")
            or ""
        ).strip()

        email = str(lead.get("email") or "").strip()

        if not contact_name:
            return validation_failure(
                "Contact name is required."
            )

        if not email or "@" not in email:
            return validation_failure(
                "A valid email address is required."
            )

        domain = email.split("@")[-1]

        if "." not in domain:
            return validation_failure(
                "Please provide a valid email address."
            )

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

    except Exception as exc:
        failure = classify_workflow_failure(
            exc,
            stage="intake_validation",
            lead_created=bool(state.get("lead_id")),
        )

        return {
            **failure,
            "stage": "validation_failed",
            "route": "error",
            "error": str(exc),
        }

# ============================================================
# AGENT 2 — DUPLICATE DETECTION
# ============================================================

def duplicate_detection_agent(state: LeadWorkflowState):
    try:
        lead_data = state.get("lead_data") or {}

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

    except Exception as exc:
        failure = classify_workflow_failure(
            exc,
            stage="duplicate_detection",
            lead_created=bool(state.get("lead_id")),
        )

        return {
            **failure,
            "duplicate_matches": [],
            "stage": "duplicate_detection_failed",
            "route": "error",
            "error": str(exc),
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

Return valid JSON only, using this exact structure:

{{
    "score": 85,
    "category": "high_fit",
    "reasoning": "A credible, funded business opportunity with a clear need.",
    "missing_information": [
        "Preferred technology stack"
    ],
    "critical_missing_information": [],
    "additional_discovery_information": [
        "Preferred technology stack"
    ],
    "recommended_next_action": "Proceed to sales discovery.",
    "human_review_required": false
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

QUALIFICATION AND ROUTING RULES:

1. HIGH FIT AND MEDIUM FIT:
Use high_fit or medium_fit when the company, industry,
business need, and available information establish a credible
potential customer.

2. CRITICAL MISSING INFORMATION:
Use critical_missing_information for missing details that
prevent the sales team from responsibly proceeding with
the opportunity.

Examples:
- Sample count when the project scope cannot be estimated
  without it.
- Sequencing data volume when essential to defining the service.
- No sufficiently clear project requirement or service scope.
- Unclear project objective that prevents understanding
  what the customer actually needs.

3. NON-BLOCKING DISCOVERY INFORMATION:
Use additional_discovery_information for useful details
that can be collected during normal sales discovery.

Examples:
- Preferred technology stack.
- Desired project duration and milestones.
- Preferred report format.
- Preferred communication frequency.
- Other technical preferences that do not prevent
  an initial sales discussion.

These details MUST NOT automatically stop an otherwise
qualified lead from proceeding to sales assignment.

4. MISSING INFORMATION:
The missing_information field must contain the combined
list of critical and non-blocking missing details.

Do not classify every missing detail as critical.

5. REQUEST INFORMATION:
For a credible high_fit or medium_fit lead, use
critical_missing_information when essential project details
are genuinely required before sales assignment.

Ordinary technical discovery questions alone must not
trigger this route.

6. HUMAN REVIEW:
Use needs_review and set human_review_required to true
when information is contradictory, unreliable, insufficient
to establish a credible opportunity, or requires genuine
human judgment.

Do not use human review merely because ordinary project
details are missing.

7. LOW FIT:
Use low_fit for leads that do not represent a credible
potential customer for the offered services.

A low-fit lead must remain low_fit even if it also has
missing information.

Do not use missing information to turn an obvious low-fit
lead into a request-information opportunity.

8. DO NOT INFLATE THE SCORE.
Assess the actual business opportunity, budget, timeline,
industry relevance, and business need.

IMPORTANT EXAMPLES:

Example A:
A funded, high-fit genomics project has a clear service
requirement and immediate timeline, but has not specified
its preferred technology stack or project milestones.

Expected:
high_fit
critical_missing_information: []
additional_discovery_information: technical preferences
human_review_required: false

Example B:
A credible WGS customer has a budget and timeline but
has not provided sample count or sequencing data volume,
which are necessary to define the requested project.

Expected:
high_fit or medium_fit
critical_missing_information: sample count and data volume
human_review_required: false

Example C:
A lead gives contradictory statements about project approval
and budget authorization.

Expected:
needs_review
human_review_required: true

Example D:
A small retail business has no genomics or bioinformatics
requirement, no relevant project, and no purchasing plans.

Expected:
low_fit
human_review_required: false
"""

        response = client.chat.completions.create(
            model=get_groq_model(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a careful B2B lead qualification "
                        "assistant. Return valid JSON only and "
                        "distinguish critical missing information "
                        "from ordinary discovery details."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=1100,
        )

        content = clean_json_response(
            response.choices[0].message.content
        )

        result = json.loads(content)

        if not isinstance(result, dict):
            raise ValueError(
                "The AI qualification response was not a JSON object."
            )

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

        if (
            str(original_category).strip().lower()
            != normalized_category
        ):
            result["original_ai_category"] = str(original_category)

        # ----------------------------------------------------
        # NORMALIZE MISSING INFORMATION
        # ----------------------------------------------------

        def normalize_information_list(value):
            if value is None:
                return []

            if not isinstance(value, list):
                value = [value]

            return [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

        original_missing = normalize_information_list(
            result.get("missing_information", [])
        )

        critical_missing = normalize_information_list(
            result.get("critical_missing_information", [])
        )

        additional_discovery = normalize_information_list(
            result.get("additional_discovery_information", [])
        )

        # ----------------------------------------------------
        # BACKWARD COMPATIBILITY
        # ----------------------------------------------------

        if "critical_missing_information" not in result:
            critical_missing = original_missing

        all_missing = list(
            dict.fromkeys(
                critical_missing + additional_discovery
            )
        )

        for item in original_missing:
            if item not in all_missing:
                all_missing.append(item)

        result["missing_information"] = critical_missing

        result["critical_missing_information"] = critical_missing

        result["additional_discovery_information"] = (
            additional_discovery
        )

        result["all_missing_information"] = all_missing

        # ----------------------------------------------------
        # NORMALIZE REASONING AND NEXT ACTION
        # ----------------------------------------------------

        result.setdefault(
            "reasoning",
            "No reasoning was returned.",
        )

        result.setdefault(
            "recommended_next_action",
            "Review the lead manually.",
        )

        # ----------------------------------------------------
        # NORMALIZE HUMAN REVIEW FLAG
        # ----------------------------------------------------

        human_review_value = result.get(
            "human_review_required",
            True,
        )

        if isinstance(human_review_value, str):
            human_review_value = (
                human_review_value.strip().lower()
                in {"true", "yes", "1"}
            )

        result["human_review_required"] = bool(
            human_review_value
        )

        if normalized_category == "needs_review":
            result["human_review_required"] = True

        # ----------------------------------------------------
        # VALIDATE QUALIFICATION CATEGORY
        # ----------------------------------------------------

        if result["category"] not in ALLOWED_QUALIFICATION_CATEGORIES:
            raise ValueError(
                "Invalid qualification category generated."
            )

        # ----------------------------------------------------
        # SAVE QUALIFICATION RESULT
        # ----------------------------------------------------

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
# AGENT 5 — HISTORICAL MEMORY RETRIEVAL (PHASE 12.2)
# ============================================================

def memory_retrieval_agent(state: LeadWorkflowState):
    """
    Retrieve anonymized historical outcomes relevant to the current lead.

    Memory retrieval is informational at this stage. It does not change
    qualification results or decision routing. The existing AI Decision
    Agent will continue to use its current rules until the later
    memory-aware decision-making step.

    If memory retrieval fails, the workflow continues with an empty
    memory list rather than interrupting lead processing.
    """

    lead_id = state.get("lead_id")
    lead = state.get("lead") or state.get("lead_data") or {}
    qualification = state.get("qualification") or {}

    try:
        memories = get_relevant_agent_memories(
            lead_data=lead,
            qualification=qualification,
            limit=5,
        )

        if not isinstance(memories, list):
            memories = []

        # Keep the audit event concise. Historical memory contents are
        # stored in workflow state, not copied into the audit event.
        create_workflow_event(
            lead_id,
            "agent_memory_retrieval_completed",
            (
                f"Agent Memory retrieved {len(memories)} relevant "
                "historical workflow outcome(s)."
            ),
            details={
                "memory_count": len(memories),
                "memory_limit": 5,
                "industry": lead.get("industry"),
                "qualification_category": qualification.get("category"),
                "retrieval_status": "completed",
                "memory_used_for_decision": False,
            },
        )

        return {
            "agent_memories": memories,
            "memory_retrieval_status": "completed",
            "memory_retrieval_count": len(memories),
            "stage": "memory_retrieval_completed",
            "route": "continue",
        }

    except Exception as exc:
        # Memory is an enhancement, not a dependency for core workflow
        # execution. Preserve the existing qualification and decision path.
        try:
            create_workflow_event(
                lead_id,
                "agent_memory_retrieval_failed",
                (
                    "Historical memory retrieval failed. "
                    "The workflow continued without memory context."
                ),
                event_status="warning",
                details={
                    "retrieval_status": "failed",
                    "memory_count": 0,
                    "error": str(exc),
                    "workflow_continued": True,
                },
            )
        except Exception:
            pass

        return {
            "agent_memories": [],
            "memory_retrieval_status": "failed",
            "memory_retrieval_count": 0,
            "stage": "memory_retrieval_skipped",
            "route": "continue",
            "email_warning": (
                "Historical memory could not be retrieved. "
                "The lead workflow continued normally."
            ),
        }


# ============================================================
# PHASE 12.4.1 — MEMORY CONTEXT PREPARATION
# ============================================================

def prepare_agent_memory_context(memories):
    """
    Convert retrieved historical memories into a structured,
    anonymized context for the AI Decision Agent.

    Historical memories provide supporting evidence only.
    They must never override current qualification results
    or deterministic workflow safety rules.
    """

    if not isinstance(memories, list):
        memories = []

    outcomes = []
    feedback = []

    for memory in memories[:5]:

        if not isinstance(memory, dict):
            continue

        record_type = str(
            memory.get("record_type") or ""
        ).strip().lower()

        common_context = {
            "industry": memory.get("industry"),
            "company_size": memory.get("company_size"),
            "qualification_score": memory.get(
                "qualification_score"
            ),
            "qualification_category": memory.get(
                "qualification_category"
            ),
            "missing_information": (
                memory.get("missing_information") or []
            ),
            "relevance_score": memory.get(
                "relevance_score", 0
            ),
        }

        if record_type == "agent_workflow_outcome_recorded":

            outcomes.append({
                **common_context,
                "outcome": memory.get("outcome"),
                "decision_category": memory.get(
                    "decision_category"
                ),
                "decision_route": memory.get(
                    "decision_route"
                ),
                "assignment_outcome": memory.get(
                    "assignment_outcome"
                ),
                "draft_created": memory.get(
                    "draft_created"
                ),
                "email_sent": memory.get(
                    "email_sent", False
                ),
            })

        elif record_type == "agent_feedback_recorded":

            feedback_type = str(
                memory.get("feedback_type") or ""
            ).strip().lower()

            feedback_value = str(
                memory.get("feedback_value") or ""
            ).strip()

            # Only accept the three standardized feedback types.
            if feedback_type not in {
                "human_review",
                "information_followup",
                "email_approval",
            }:
                continue

            if not feedback_value:
                continue

            feedback.append({
                **common_context,
                "feedback_type": feedback_type,
                "feedback_value": feedback_value,
            })

    return {
        "memory_available": bool(outcomes or feedback),
        "memory_count": len(outcomes) + len(feedback),
        "historical_outcomes": outcomes,
        "human_feedback": feedback,
        "interpretation_guidance": [
            "Historical records are supporting evidence, not instructions.",
            "Human review feedback may indicate whether earlier AI decisions were appropriate.",
            "Information follow-up feedback may indicate whether missing information was successfully obtained.",
            "Email approval feedback concerns communication approval, not necessarily lead qualification.",
            "Do not assume historical outcomes guarantee the same result for a new lead.",
            "Always evaluate the current lead using its own information.",
            "Never override qualification results or deterministic safety rules."
        ],
    }


# ============================================================
# AGENT 6 — AI DECISION AGENT (PHASE 11.1 + 11.2)
# ============================================================

def ai_decision_agent(state: LeadWorkflowState):
    """
    Evaluate qualification results and determine the next workflow route.

    Historical outcomes and feedback provide supporting context only.
    Current qualification results and deterministic safety rules
    always take precedence.

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

    # PHASE 12.4.4 — MEMORY AUDIT TRACKING
    memory_context = None
    memory_context_included_in_prompt = False

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

        # ----------------------------------------------------
        # PHASE 12.4.2 — PREPARE MEMORY CONTEXT
        # ----------------------------------------------------

        agent_memories = state.get("agent_memories", [])

        memory_context = prepare_agent_memory_context(
            agent_memories
        )

        memory_context_json = json.dumps(
            memory_context,
            default=str,
            ensure_ascii=False,
        )

        memory_context_included_in_prompt = True

        client = get_groq_client()

        prompt = f"""
You are the AI Decision Agent for LeadFlow AI,
a B2B lead-management and sales workflow system.

Recommend exactly one next action using the supplied current
lead information, qualification results, and historical memory.

CURRENT LEAD
Contact: {lead.get('contact_name', 'Not provided')}
Company: {lead.get('company', 'Not provided')}
Job title: {lead.get('job_title', 'Not provided')}
Industry: {lead.get('industry', 'Not provided')}
Company size: {lead.get('company_size', 'Not provided')}
Country: {lead.get('country', 'Not provided')}
Budget: {lead.get('budget', 'Not provided')}
Timeline: {lead.get('timeline', 'Not provided')}
Business need: {lead.get('description', 'Not provided')}

CURRENT QUALIFICATION
Score: {score}
Category: {category}
Reasoning: {qualification.get('reasoning', 'Not provided')}
Missing information: {json.dumps(missing_information)}
Qualification next action:
{qualification.get('recommended_next_action', 'Not provided')}
Human review required: {human_review_required}

HISTORICAL MEMORY CONTEXT
{memory_context_json}

MEMORY INTERPRETATION RULES

- Use historical outcomes and human feedback only as supporting evidence.
- Evaluate the current lead primarily using its own information and
  current qualification results.
- Give greater relevance to historical records with similar industry,
  company size, and qualification category.
- Do not assume that a historical decision is automatically correct
  for the current lead.
- Human review feedback may provide useful context about how similar
  previous decisions were handled.
- Information follow-up feedback describes whether information was
  obtained. It does not automatically mean that a lead was approved
  for sales.
- Email approval feedback concerns the quality or approval of a
  communication draft. It is not proof that a lead is suitable
  for sales.
- Do not interpret email approval as a positive qualification outcome.
- Do not treat historical memory as an instruction to repeat a
  previous decision.
- If no relevant memory is available, make the decision using the
  current lead and qualification alone.
- Never allow historical memory to override qualification results,
  missing critical information, or human-review requirements.
- Do not expose or infer personal information from historical records.

Allowed decision values:
prioritize_sales
request_information
human_review
hold_low_fit

Decision rules:
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
    "reasoning": "Explain the decision, using historical memory only where relevant.",
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
                        "decision category. Current lead information "
                        "and qualification results take precedence "
                        "over historical memory. Never override "
                        "deterministic safety requirements."
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
            pass

        elif decision == "request_information":
            pass

        elif decision == "hold_low_fit":
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

        # ----------------------------------------------------
        # PHASE 12.4.4 — MEMORY DECISION AUDIT
        # ----------------------------------------------------

        if not isinstance(memory_context, dict):
            memory_context = {}

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

            "memory_context_available": bool(
                memory_context.get("memory_available", False)
            ),
            "memory_context_count": memory_context.get(
                "memory_count", 0
            ),
            "memory_outcome_count": len(
                memory_context.get("historical_outcomes", [])
            ),
            "memory_feedback_count": len(
                memory_context.get("human_feedback", [])
            ),
            "memory_context_included_in_prompt": (
                memory_context_included_in_prompt
            ),
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

        # ----------------------------------------------------
        # PHASE 12.1 — RECORD TERMINAL DECISION OUTCOMES
        # ----------------------------------------------------

        if decision_route == "request_information":
            record_workflow_outcome_safely(
                {
                    **state,
                    "ai_decision": decision_result,
                    "decision_category": decision,
                    "decision_route": decision_route,
                    "workflow_outcome": workflow_outcome,
                },
                outcome="stopped_pending_information",
                message=(
                    "Workflow outcome recorded: lead requires "
                    "additional information before sales assignment."
                ),
                additional_details={
                    "missing_information": missing_information,
                    "recommended_next_action": recommended_next_action,
                },
            )

        elif decision_route == "human_review":
            record_workflow_outcome_safely(
                {
                    **state,
                    "ai_decision": decision_result,
                    "decision_category": decision,
                    "decision_route": decision_route,
                    "workflow_outcome": workflow_outcome,
                },
                outcome="stopped_for_human_review",
                message=(
                    "Workflow outcome recorded: lead requires "
                    "human review before sales assignment."
                ),
                additional_details={
                    "human_review_required": True,
                    "recommended_next_action": recommended_next_action,
                },
            )

        elif decision_route == "hold_low_fit":
            record_workflow_outcome_safely(
                {
                    **state,
                    "ai_decision": decision_result,
                    "decision_category": decision,
                    "decision_route": decision_route,
                    "workflow_outcome": workflow_outcome,
                },
                outcome="held_low_fit",
                message=(
                    "Workflow outcome recorded: low-fit lead "
                    "was held out of immediate sales prioritization."
                ),
                additional_details={
                    "human_review_required": False,
                    "recommended_next_action": recommended_next_action,
                },
            )

        # prioritize_sales is intentionally not recorded as a
        # final outcome here. Its workflow continues through
        # owner assignment and email draft generation.

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

            # PHASE 12.4.4 — FALLBACK MEMORY AUDIT
            "memory_context_available": bool(
                isinstance(memory_context, dict)
                and memory_context.get("memory_available", False)
            ),
            "memory_context_count": (
                memory_context.get("memory_count", 0)
                if isinstance(memory_context, dict)
                else 0
            ),
            "memory_context_included_in_prompt": (
                memory_context_included_in_prompt
            ),
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

            # ------------------------------------------------
            # PHASE 12.1 — RECORD FALLBACK OUTCOME
            # ------------------------------------------------

            record_workflow_outcome_safely(
                {
                    **state,
                    "ai_decision": fallback_decision,
                    "decision_category": "human_review",
                    "decision_route": "human_review",
                    "workflow_outcome": "stopped_for_human_review",
                },
                outcome="stopped_for_human_review",
                message=(
                    "Workflow outcome recorded: the Decision Agent "
                    "failed and safely routed the lead to human review."
                ),
                additional_details={
                    "decision_agent_fallback": True,
                    "decision_error": str(exc),
                    "human_review_required": True,
                },
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
    """
    Generate a follow-up email draft.

    Recovery behavior:
    1. Try Groq email generation.
    2. Retry once if the response is empty or incomplete.
    3. Generate a safe fallback email if both attempts fail.
    4. Save the draft for human review.

    This agent never sends emails.
    """

    # --------------------------------------------------------
    # RETRIEVE LEAD
    # --------------------------------------------------------

    try:
        lead = get_lead_by_id(state["lead_id"])

    except Exception as exc:
        record_workflow_outcome_safely(
            {
                **state,
                "stage": "email_draft_failed",
            },
            outcome="sales_workflow_email_draft_failed",
            message=(
                "Sales workflow reached the email stage, but "
                "the lead could not be retrieved for draft generation."
            ),
            additional_details={
                "draft_created": False,
                "failure_reason": str(exc),
            },
        )

        return {
            "stage": "email_draft_failed",
            "email_warning": (
                f"Lead retrieval failed during email generation: {exc}"
            ),
            "route": "complete",
        }

    if not lead:
        record_workflow_outcome_safely(
            {
                **state,
                "stage": "email_draft_failed",
            },
            outcome="sales_workflow_email_draft_failed",
            message=(
                "Sales workflow reached the email stage, but "
                "the lead could not be retrieved for draft generation."
            ),
            additional_details={
                "draft_created": False,
                "failure_reason": "lead_not_found",
            },
        )

        return {
            "stage": "email_draft_failed",
            "email_warning": (
                "Lead could not be retrieved for email generation."
            ),
            "route": "complete",
        }

    # --------------------------------------------------------
    # CONSENT CHECK
    # --------------------------------------------------------

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

        record_workflow_outcome_safely(
            {
                **state,
                "stage": "completed_no_email_consent",
            },
            outcome="sales_workflow_completed_without_email_consent",
            message=(
                "Sales workflow completed without generating an "
                "email draft because contact consent was not recorded."
            ),
            additional_details={
                "draft_created": False,
                "email_skipped": True,
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

    # --------------------------------------------------------
    # EMAIL GENERATION AND SAVING
    # --------------------------------------------------------

    draft_id = None

    try:
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

        client = get_groq_client()

        subject = ""
        body = ""
        ai_generation_success = False
        generation_error = ""

        # ----------------------------------------------------
        # ATTEMPT 1 + ONE RETRY
        # ----------------------------------------------------

        for attempt in range(1, 3):
            try:
                response = client.chat.completions.create(
                    model=get_groq_model(),
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You write accurate, personalized, "
                                "professional B2B sales emails. "
                                "Always return both a subject and a "
                                "complete body using the exact requested "
                                "format. Never return an empty response."
                            ),
                        },
                        {
                            "role": "user",
                            "content": prompt,
                        },
                    ],
                    temperature=0.2,
                    max_tokens=1200,
                )

                output = (
                    response.choices[0].message.content or ""
                ).strip()

                subject, body = parse_email_response(output)

                ai_generation_success = True
                break

            except Exception as exc:
                generation_error = str(exc)

                if attempt == 1:
                    continue

        # ----------------------------------------------------
        # FALLBACK EMAIL
        # ----------------------------------------------------

        if not ai_generation_success:

            contact_name = (
                lead.get("contact_name") or "there"
            ).strip()

            company_name = (
                lead.get("company") or "your organization"
            ).strip()

            business_need = (
                lead.get("description") or ""
            ).strip()

            subject = (
                f"Following up on your enquiry - {company_name}"
            )

            if business_need:
                body = f"""Hello {contact_name},

Thank you for your interest in our services and for sharing information about your requirements.

We would welcome the opportunity to understand your needs regarding {business_need[:350]}

Our team would be happy to discuss the relevant services, understand your project requirements, and explore how we may be able to assist.

Would you be available to share any additional details about your project or suggest a convenient time for an initial discussion?

We look forward to hearing from you.

Best regards,
The {owner_name} Team"""
            else:
                body = f"""Hello {contact_name},

Thank you for your interest in our services.

We would welcome the opportunity to learn more about your organization's requirements and understand how our team may be able to assist.

Could you please share some additional details about your project and the services you are looking for?

We look forward to hearing from you.

Best regards,
The {owner_name} Team"""

        # ----------------------------------------------------
        # SAVE THE DRAFT
        # ----------------------------------------------------

        draft_id = save_email_draft(
            state["lead_id"],
            lead.get("email"),
            subject,
            body,
        )

        if not draft_id:
            raise ValueError(
                "The email draft could not be saved to the database."
            )

        generation_method = (
            "ai_generated"
            if ai_generation_success
            else "fallback_generated"
        )

        create_workflow_event(
            state["lead_id"],
            "agent_email_draft_created",
            (
                "LangGraph created an email draft for human review."
            ),
            details={
                "email_draft_id": draft_id,
                "subject": subject,
                "generation_method": generation_method,
                "ai_generation_success": ai_generation_success,
                "approval_required": True,
                "email_sent": False,
            },
        )

        # Record fallback use separately for easier monitoring.
        if not ai_generation_success:
            create_workflow_event(
                state["lead_id"],
                "agent_email_fallback_used",
                (
                    "AI email generation failed after two attempts. "
                    "A fallback email draft was created and saved "
                    "for human review."
                ),
                details={
                    "email_draft_id": draft_id,
                    "generation_error": generation_error,
                    "generation_method": "fallback_generated",
                },
            )

        # ----------------------------------------------------
        # PHASE 12.1 — FINAL SALES WORKFLOW OUTCOME
        # ----------------------------------------------------

        if ai_generation_success:
            final_outcome = (
                "sales_workflow_completed_ai_email_draft_saved"
            )

            final_message = (
                "Sales workflow completed successfully. "
                "An AI-generated email draft was saved for human review."
            )

        else:
            final_outcome = (
                "sales_workflow_completed_fallback_email_draft_saved"
            )

            final_message = (
                "Sales workflow completed with a fallback email draft. "
                "The draft was saved for human review."
            )

        # Preserve the distinction between successful email
        # generation and unsuccessful/pending owner assignment.
        if not state.get("assignment_success"):
            if ai_generation_success:
                final_outcome = (
                    "sales_workflow_completed_with_assignment_pending"
                )
            else:
                final_outcome = (
                    "sales_workflow_completed_with_assignment_pending_and_fallback_email"
                )

            final_message = (
                "The email draft was saved, but automatic sales-owner "
                "assignment was unsuccessful or remains pending."
            )

        record_workflow_outcome_safely(
            {
                **state,
                "draft_id": draft_id,
                "email_subject": subject,
                "email_body": body,
                "stage": "workflow_completed",
            },
            outcome=final_outcome,
            message=final_message,
            additional_details={
                "draft_created": True,
                "email_draft_id": draft_id,
                "generation_method": generation_method,
                "ai_generation_success": ai_generation_success,
                "assignment_success": bool(
                    state.get("assignment_success")
                ),
                "email_sent": False,
                "approval_required": True,
            },
        )

        return {
            "draft_id": draft_id,
            "email_subject": subject,
            "email_body": body,
            "email_generation_method": generation_method,
            "stage": "workflow_completed",
            "route": "complete",
            "email_warning": (
                ""
                if ai_generation_success
                else (
                    "Groq did not return a valid email after two "
                    "attempts. A fallback draft was saved for review."
                )
            ),
        }

    except Exception as exc:
        try:
            create_workflow_event(
                state["lead_id"],
                "agent_email_draft_failed",
                "Email draft generation and recovery failed.",
                details={
                    "error": str(exc),
                    "draft_created": bool(draft_id),
                    "email_draft_id": draft_id,
                },
            )
        except Exception:
            pass

        record_workflow_outcome_safely(
            {
                **state,
                "draft_id": draft_id,
                "stage": "completed_email_warning",
            },
            outcome=(
                "sales_workflow_email_draft_saved_but_audit_failed"
                if draft_id
                else "sales_workflow_email_draft_failed"
            ),
            message=(
                "The email stage encountered an error. "
                + (
                    "A draft was saved, but a later email-stage operation failed."
                    if draft_id
                    else "No email draft was successfully saved."
                )
            ),
            additional_details={
                "draft_created": bool(draft_id),
                "email_draft_id": draft_id,
                "email_sent": False,
                "failure_reason": str(exc),
            },
        )

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


def route_memory_retrieval(state):
    # Memory retrieval must never block the core workflow.
    return "continue"


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
    graph.add_node("memory_retrieval", memory_retrieval_agent)
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
            "continue": "memory_retrieval",
            "error": END,
        },
    )

    # Phase 12.2: Retrieve relevant historical outcomes before the
    # existing AI Decision Agent. Retrieval failure still continues.
    graph.add_conditional_edges(
        "memory_retrieval",
        route_memory_retrieval,
        {
            "continue": "ai_decision",
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

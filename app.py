import json, os, re
import streamlit as st
from groq import Groq
from database import *

st.set_page_config(page_title="LeadFlow AI", page_icon="🟣", layout="wide")
st.markdown("""<style>.stApp{background:linear-gradient(135deg,#10101d,#17132b,#20143b);color:#f5f3ff}[data-testid="stSidebar"]{background:#11101d}h1,h2,h3,p,label{color:#f5f3ff}div[data-testid="stMetricValue"]{color:#d8b4fe}.stButton>button{border-radius:10px;border:1px solid #8b5cf6}</style>""",unsafe_allow_html=True)
st.title("🟣 LeadFlow AI")
st.caption("Lead intake, duplicate intelligence, and AI-assisted qualification")
for k,v in [("pending_lead",None),("pending_matches",[]),("confirm_possible_duplicate",False),("save_message",None),("last_qualification",None)]:
    if k not in st.session_state: st.session_state[k]=v
with st.sidebar:
    st.markdown("## LeadFlow AI")
    page=st.radio("Workspace",["Overview","Lead Intake","All Leads","AI Qualification","Workflow History","Database Setup"])
    st.caption("AI recommendations require human review.")
try:
    if not get_database_url(): st.warning("Add NEON_DATABASE_URL in Streamlit Community Cloud → App settings → Secrets."); st.stop()
    if not test_connection(): st.error("Could not connect to Neon. Check NEON_DATABASE_URL."); st.stop()
    initialize_schema()
except Exception as e:
    st.error(f"Database setup failed: {e}"); st.stop()

def qualify(lead):
    key=None
    try: key=st.secrets.get("GROQ_API_KEY")
    except Exception: pass
    key=key or os.getenv("GROQ_API_KEY")
    if not key: raise RuntimeError("GROQ_API_KEY is missing. Add it in Streamlit Community Cloud → App settings → Secrets. Never put it in GitHub or chat.")
    model=None
    try: model=st.secrets.get("GROQ_MODEL")
    except Exception: pass
    model=model or os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b"
    fields=["lead_reference","contact_name","email","company","website","job_title","industry","country","company_size","budget","timeline","description"]
    data={k:lead.get(k) for k in fields}
    prompt=f"""Assess this B2B sales lead using only the supplied facts; do not invent details. Return valid JSON only with score (integer 0-100), category (high_fit, medium_fit, low_fit, needs_review), priority (urgent, high, medium, low), reasoning (string), missing_information (array of strings), recommended_next_action (string), human_review_required (boolean). Use needs_review when evidence is insufficient. This is decision support, not a final decision. Lead: {json.dumps(data,default=str)}"""
    res=Groq(api_key=key).chat.completions.create(model=model,messages=[{"role":"system","content":"You are a cautious sales qualification assistant. Return valid JSON only."},{"role":"user","content":prompt}],temperature=0.1,max_tokens=900)
    raw=re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$","",res.choices[0].message.content or "",flags=re.I)
    m=re.search(r"\{.*\}",raw,re.S)
    if not m: raise ValueError("The AI response was not valid JSON. Please retry.")
    x=json.loads(m.group())
    cats={"high_fit","medium_fit","low_fit","needs_review"}; priorities={"urgent","high","medium","low"}
    cat=str(x.get("category","needs_review")).lower()
    pr=str(x.get("priority","medium")).lower()
    if cat not in cats: cat="needs_review"
    if pr not in priorities: pr="medium"
    try: score=max(0,min(100,int(x.get("score",0))))
    except (ValueError,TypeError): score=0; cat="needs_review"
    missing=x.get("missing_information",[])
    if not isinstance(missing,list): missing=[str(missing)]
    return {"model_name":model,"score":score,"category":cat,"priority":pr,"reasoning":str(x.get("reasoning","No explanation supplied.")),"missing_information":[str(i) for i in missing],"recommended_next_action":str(x.get("recommended_next_action","Review this lead manually.")),"human_review_required":bool(x.get("human_review_required",True))}

if page=="Overview":
    leads=get_leads(); counts=get_table_counts()
    a,b,c,d=st.columns(4); a.metric("Total leads",counts["leads"]); b.metric("Qualification results",counts["qualification_results"]); c.metric("Workflow events",counts["workflow_events"]); d.metric("Needs review",sum(x.get("status")=="needs_review" for x in leads))
    st.subheader("Recent leads"); st.dataframe(leads[:10],use_container_width=True,hide_index=True) if leads else st.info("No leads yet. Add your first lead from Lead Intake.")
    st.caption("Potential duplicates are never merged automatically. AI recommendations are advisory.")
elif page=="Lead Intake":
    st.subheader("Lead Intake")
    if st.session_state.save_message: st.success(st.session_state.save_message); st.session_state.save_message=None
    with st.form("lead_form",clear_on_submit=False):
        c1,c2=st.columns(2)
        with c1:
            name=st.text_input("Contact name *"); email=st.text_input("Business email *"); company=st.text_input("Company *"); website=st.text_input("Website"); title=st.text_input("Job title")
        with c2:
            industry=st.text_input("Industry"); country=st.text_input("Country"); size=st.selectbox("Company size",["","1-10","11-50","51-200","201-1000","1000+"]); budget=st.text_input("Budget"); timeline=st.selectbox("Buying timeline",["","Immediate","Within 1 month","1-3 months","3-6 months","6+ months","Unknown"])
        desc=st.text_area("Lead notes / business need")
        submitted=st.form_submit_button("Check lead and continue",type="primary")
    if submitted:
        lead={"contact_name":name.strip(),"email":email.strip(),"company":company.strip(),"website":website.strip(),"job_title":title.strip(),"industry":industry.strip(),"country":country.strip(),"company_size":size,"budget":budget.strip(),"timeline":timeline,"description":desc.strip()}
        missing=[label for label,val in [("Contact name",lead["contact_name"]),("Email",lead["email"]),("Company",lead["company"])] if not val]
        if missing: st.error("Please complete required fields: "+", ".join(missing))
        elif "@" not in lead["email"] or "." not in lead["email"].split("@")[-1]: st.error("Please enter a valid email address.")
        else:
            try:
                matches=find_potential_duplicates(lead)
                exact=[x for x in matches if x.get("match_type")=="exact_email"]
                if exact:
                    st.error("A lead with this email already exists. Exact email duplicates cannot be saved."); st.dataframe(exact,use_container_width=True,hide_index=True)
                    st.session_state.pending_lead=None; st.session_state.pending_matches=[]
                elif matches:
                    st.session_state.pending_lead=lead; st.session_state.pending_matches=matches; st.session_state.confirm_possible_duplicate=False
                    st.success("Potential matches found. Review them below, then confirm if this is a separate lead.")
                else:
                    ref=create_lead(lead); st.session_state.save_message=f"Lead saved successfully. Reference: {ref}"; st.rerun()
            except Exception as e: st.error(f"Lead check/save failed: {e}")
    # Keep confirmation outside submitted branch so checkbox reruns do not discard pending lead.
    if st.session_state.pending_lead:
        st.warning("Possible duplicates require review.")
        st.dataframe(st.session_state.pending_matches,use_container_width=True,hide_index=True)
        st.checkbox("I reviewed the matches and confirm this is a separate lead.",key="confirm_possible_duplicate")
        if st.button("Confirm and save lead",type="primary"):
            if not st.session_state.confirm_possible_duplicate: st.error("Tick the confirmation box after reviewing matches.")
            else:
                try:
                    ref=create_lead(st.session_state.pending_lead)
                    st.session_state.save_message=f"Confirmed lead saved successfully. Reference: {ref}"
                    st.session_state.pending_lead=None; st.session_state.pending_matches=[]; st.session_state.confirm_possible_duplicate=False
                    st.rerun()
                except Exception as e: st.error(f"Could not save confirmed lead: {e}")
elif page=="All Leads":
    st.subheader("All Leads"); leads=get_leads()
    if not leads: st.info("No leads saved yet.")
    else:
        q=st.text_input("Search leads",placeholder="Name, email, company, reference")
        statuses=sorted({str(x.get("status","new")) for x in leads}); status=st.selectbox("Filter by status",["All statuses"]+statuses)
        filtered=[x for x in leads if q.lower() in " ".join(str(x.get(k,"")) for k in ["lead_reference","contact_name","email","company"]).lower() and (status=="All statuses" or x.get("status")==status)]
        st.dataframe(filtered,use_container_width=True,hide_index=True)
elif page=="AI Qualification":
    st.subheader("Phase 5 — AI Lead Qualification"); leads=get_leads()
    if not leads: st.info("Add a lead first using Lead Intake.")
    else:
        choices={f"{x.get('lead_reference')} — {x.get('contact_name')} / {x.get('company')}":x for x in leads}
        label=st.selectbox("Select a lead to qualify",list(choices)); lead=choices[label]
        with st.expander("Lead details",expanded=True):
            st.write({k:lead.get(k) for k in ["email","industry","job_title","country","company_size","budget","timeline","description"]})
        if st.button("Qualify selected lead with AI",type="primary"):
            with st.spinner("Groq is assessing the lead…"):
                try:
                    result=qualify(lead); save_qualification_result(lead["id"],result); update_lead_qualification(lead["id"],result["category"],result["priority"])
                    st.session_state.last_qualification={"lead_reference":lead["lead_reference"],**result}
                    st.success("Qualification saved to Neon. Review the recommendation before acting.")
                except Exception as e: st.error(f"Qualification failed; no result was saved: {e}")
        last=st.session_state.last_qualification
        if last and last.get("lead_reference")==lead.get("lead_reference"):
            st.markdown("### Latest AI assessment")
            a,b,c=st.columns(3); a.metric("Fit score",f"{last['score']}/100"); b.metric("Category",last["category"].replace("_"," ").title()); c.metric("Priority",last["priority"].title())
            st.write("**Reasoning**"); st.write(last["reasoning"]); st.write("**Missing information**")
            st.write("\n".join("- "+x for x in last["missing_information"]) if last["missing_information"] else "No key missing information identified.")
            st.write("**Recommended next action**"); st.info(last["recommended_next_action"])
            st.warning("Human review required: "+("Yes" if last["human_review_required"] else "AI marked review optional; verify before action."))
        history=get_qualification_results(lead["id"])
        if history: st.markdown("### Saved qualification history"); st.dataframe(history,use_container_width=True,hide_index=True)
elif page=="Workflow History":
    st.subheader("Workflow History"); events=get_workflow_events()
    st.dataframe(events,use_container_width=True,hide_index=True) if events else st.info("No workflow events recorded yet.")
elif page=="Database Setup":
    st.subheader("Database Setup"); st.success("Connected to Neon PostgreSQL.")
    st.dataframe([{"Table":k,"Records":v} for k,v in get_table_counts().items()],use_container_width=True,hide_index=True)
    st.caption("Expected tables: leads, sales_owners, qualification_results, email_drafts, workflow_events.")

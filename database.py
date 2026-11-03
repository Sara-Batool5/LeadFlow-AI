import json, os, uuid
from datetime import datetime, timezone
import psycopg
from psycopg.rows import dict_row

class DatabaseConfigurationError(RuntimeError): pass

def get_database_url():
    try:
        import streamlit as st
        value=st.secrets.get("NEON_DATABASE_URL")
    except Exception: value=None
    return value or os.getenv("NEON_DATABASE_URL")

def _connect():
    url=get_database_url()
    if not url: raise DatabaseConfigurationError("NEON_DATABASE_URL is not configured.")
    return psycopg.connect(url,row_factory=dict_row,connect_timeout=15)

def test_connection():
    try:
        with _connect() as conn:
            with conn.cursor() as cur: cur.execute("SELECT 1"); cur.fetchone()
        return True
    except Exception: return False

def initialize_schema():
    sqls=[
    """CREATE TABLE IF NOT EXISTS leads (id UUID PRIMARY KEY, lead_reference TEXT UNIQUE NOT NULL, contact_name TEXT NOT NULL, email TEXT NOT NULL, company TEXT NOT NULL, website TEXT, job_title TEXT, industry TEXT, country TEXT, company_size TEXT, budget TEXT, timeline TEXT, description TEXT, status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','qualifying','qualified','needs_review','assigned','contacted','closed_won','closed_lost')), priority TEXT NOT NULL DEFAULT 'unassessed' CHECK(priority IN ('unassessed','low','medium','high','urgent')), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS sales_owners (id UUID PRIMARY KEY, name TEXT NOT NULL, email TEXT, territory TEXT, industries TEXT, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS qualification_results (id UUID PRIMARY KEY, lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE, model_name TEXT NOT NULL, score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100), category TEXT NOT NULL CHECK(category IN ('high_fit','medium_fit','low_fit','needs_review')), reasoning TEXT NOT NULL, missing_information JSONB NOT NULL DEFAULT '[]'::jsonb, recommended_next_action TEXT NOT NULL, human_review_required BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS email_drafts (id UUID PRIMARY KEY, lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS workflow_events (id UUID PRIMARY KEY, lead_id UUID REFERENCES leads(id) ON DELETE SET NULL, event_type TEXT NOT NULL, message TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'system', details JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    "CREATE INDEX IF NOT EXISTS idx_leads_email_lower ON leads (LOWER(email))",
    "CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_workflow_events_created_at ON workflow_events (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_qualification_lead_created ON qualification_results (lead_id, created_at DESC)"]
    with _connect() as conn:
        with conn.cursor() as cur:
            for sql in sqls: cur.execute(sql)

def get_table_counts():
    result={}
    with _connect() as conn:
        with conn.cursor() as cur:
            for table in ["leads","sales_owners","qualification_results","email_drafts","workflow_events"]:
                cur.execute(f"SELECT COUNT(*) AS count FROM {table}"); result[table]=int(cur.fetchone()["count"])
    return result

def _website(v):
    v=(v or "").strip().lower().replace("https://","").replace("http://","").split("/")[0]
    return v.removeprefix("www.")
def _domain(v): return v.strip().lower().split("@")[-1] if v and "@" in v else ""
def _free(d): return d in {"gmail.com","yahoo.com","hotmail.com","outlook.com","live.com","icloud.com","aol.com","proton.me","protonmail.com","mail.com","yandex.com","gmx.com"}

def find_potential_duplicates(lead):
    email=(lead.get("email") or "").strip().lower(); company=(lead.get("company") or "").strip().lower(); name=(lead.get("contact_name") or "").strip().lower(); website=_website(lead.get("website")); domain=_domain(email)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,lead_reference,contact_name,email,company,website,status,created_at FROM leads ORDER BY created_at DESC LIMIT 500"); rows=cur.fetchall()
    found=[]
    for row in rows:
        reml=str(row.get("email") or "").strip().lower(); rco=str(row.get("company") or "").strip().lower(); rn=str(row.get("contact_name") or "").strip().lower(); rw=_website(row.get("website")); rd=_domain(reml); types=[]
        if email and email==reml: types.append("exact_email")
        else:
            if name and rn and (name==rn or name in rn or rn in name): types.append("similar_contact_name")
            if company and rco and (company==rco or company in rco or rco in company): types.append("same_or_similar_company")
            if website and rw and (website==rw or website.endswith("."+rw) or rw.endswith("."+website)): types.append("same_website_domain")
            if domain and domain==rd and not _free(domain): types.append("same_business_email_domain")
        if types:
            item=dict(row); item["match_type"]=", ".join(types); item["created_at"]=str(item.get("created_at","")); item.pop("id",None); found.append(item)
    return found[:10]

def create_lead(lead):
    lid=str(uuid.uuid4()); ref="LF-"+datetime.now(timezone.utc).strftime("%y%m%d")+"-"+uuid.uuid4().hex[:6].upper()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO leads(id,lead_reference,contact_name,email,company,website,job_title,industry,country,company_size,budget,timeline,description) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(lid,ref,lead["contact_name"],lead["email"].strip(),lead["company"],lead.get("website") or None,lead.get("job_title") or None,lead.get("industry") or None,lead.get("country") or None,lead.get("company_size") or None,lead.get("budget") or None,lead.get("timeline") or None,lead.get("description") or None))
            cur.execute("INSERT INTO workflow_events(id,lead_id,event_type,message,actor,details) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",(str(uuid.uuid4()),lid,"lead_created",f"Lead {ref} was created and saved.","lead_intake",json.dumps({"lead_reference":ref})))
    return ref

def get_leads():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id,lead_reference,contact_name,email,company,website,job_title,industry,country,company_size,budget,timeline,description,status,priority,created_at,updated_at FROM leads ORDER BY created_at DESC"); rows=cur.fetchall()
    for x in rows: x["id"]=str(x["id"]); x["created_at"]=str(x["created_at"]); x["updated_at"]=str(x["updated_at"])
    return rows

def get_workflow_events(limit=250):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT e.event_type,e.message,e.actor,e.details,e.created_at,l.lead_reference,l.contact_name,l.company FROM workflow_events e LEFT JOIN leads l ON l.id=e.lead_id ORDER BY e.created_at DESC LIMIT %s""",(limit,)); rows=cur.fetchall()
    for x in rows: x["details"]=json.dumps(x.get("details") or {},default=str); x["created_at"]=str(x["created_at"])
    return rows

def save_qualification_result(lead_id,result):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO qualification_results(id,lead_id,model_name,score,category,reasoning,missing_information,recommended_next_action,human_review_required) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)""",(str(uuid.uuid4()),lead_id,result["model_name"],result["score"],result["category"],result["reasoning"],json.dumps(result["missing_information"]),result["recommended_next_action"],result["human_review_required"]))
            cur.execute("INSERT INTO workflow_events(id,lead_id,event_type,message,actor,details) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",(str(uuid.uuid4()),lead_id,"lead_ai_qualified",f"AI qualification saved: {result['score']}/100, category {result['category']}.","groq_ai_qualification",json.dumps({k:result[k] for k in ["model_name","score","category","priority"]})))

def update_lead_qualification(lead_id,category,priority):
    status="needs_review" if category=="needs_review" else "qualified"
    with _connect() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE leads SET status=%s,priority=%s,updated_at=NOW() WHERE id=%s",(status,priority,lead_id))

def get_qualification_results(lead_id,limit=10):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_name,score,category,reasoning,missing_information,recommended_next_action,human_review_required,created_at FROM qualification_results WHERE lead_id=%s ORDER BY created_at DESC LIMIT %s",(lead_id,limit)); rows=cur.fetchall()
    for x in rows: x["missing_information"]=json.dumps(x.get("missing_information") or [],ensure_ascii=False); x["created_at"]=str(x["created_at"])
    return rows

-- LeadFlow AI combined Phase 4 fix + Phase 5 schema.
-- The application creates these tables automatically at startup.
CREATE TABLE IF NOT EXISTS leads (
 id UUID PRIMARY KEY, lead_reference TEXT UNIQUE NOT NULL, contact_name TEXT NOT NULL,
 email TEXT NOT NULL, company TEXT NOT NULL, website TEXT, job_title TEXT, industry TEXT,
 country TEXT, company_size TEXT, budget TEXT, timeline TEXT, description TEXT,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','qualifying','qualified','needs_review','assigned','contacted','closed_won','closed_lost')),
 priority TEXT NOT NULL DEFAULT 'unassessed' CHECK(priority IN ('unassessed','low','medium','high','urgent')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS sales_owners (id UUID PRIMARY KEY, name TEXT NOT NULL, email TEXT, territory TEXT, industries TEXT, active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS qualification_results (
 id UUID PRIMARY KEY, lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
 model_name TEXT NOT NULL, score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 100),
 category TEXT NOT NULL CHECK(category IN ('high_fit','medium_fit','low_fit','needs_review')),
 reasoning TEXT NOT NULL, missing_information JSONB NOT NULL DEFAULT '[]'::jsonb,
 recommended_next_action TEXT NOT NULL, human_review_required BOOLEAN NOT NULL DEFAULT TRUE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS email_drafts (id UUID PRIMARY KEY, lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE, subject TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE TABLE IF NOT EXISTS workflow_events (id UUID PRIMARY KEY, lead_id UUID REFERENCES leads(id) ON DELETE SET NULL, event_type TEXT NOT NULL, message TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'system', details JSONB NOT NULL DEFAULT '{}'::jsonb, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
CREATE INDEX IF NOT EXISTS idx_leads_email_lower ON leads(LOWER(email));
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_events_created_at ON workflow_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_qualification_lead_created ON qualification_results(lead_id,created_at DESC);

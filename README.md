# LeadFlow AI — Phase 2: Neon PostgreSQL

This phase adds a Neon PostgreSQL connection layer, initial database schema, and a Database Setup page. It does not yet accept or save submitted leads; that is Phase 3.

## 1. Create a Neon project
1. Open https://neon.tech and sign in.
2. Create a project named `leadflow-ai`.
3. Open the project dashboard and copy its PostgreSQL connection string. Keep it private.
4. Review Neon's current free-plan limits in its dashboard, as plan limits may change.

## 2. Upload the files to the existing GitHub repository
Upload the files from this ZIP into the **root** of your existing `leadflow-ai` repository:
- Replace `app.py`
- Replace `requirements.txt`
- Replace `README.md`
- Add `database.py`
- Add `schema.sql`

Do not upload the ZIP file itself. You do not need a `.gitignore` for this phase. No Codespaces, terminal, or local installation is required.

## 3. Add the database connection in Streamlit Secrets
1. Open https://share.streamlit.io and open your existing LeadFlow AI app.
2. Open the app's settings and find **Secrets** (the exact menu wording may vary).
3. Add the following TOML setting, replacing the placeholder with the **exact connection string copied from Neon**:

```toml
NEON_DATABASE_URL = "postgresql://YOUR_USER:YOUR_PASSWORD@YOUR_HOST/YOUR_DATABASE?sslmode=require"
```

Keep the entire connection string private. Do not commit it to GitHub or paste it into chat. If Neon's connection string already includes SSL parameters, use it exactly as provided.
4. Save Secrets; Streamlit should restart the app.

## 4. Test and create tables
1. Open the deployed app.
2. Select **Database Setup** in the sidebar.
3. Click **Test database connection**. You should see a successful connection message.
4. Click **Create / verify tables**. This creates the tables if they do not already exist.
5. Click **Refresh database counts**. New tables should show zero records.

## Tables
- `leads`: lead/contact fields, workflow status, priority, owner assignment, duplicate reference, and contact consent.
- `sales_owners`: owner details, specialization, availability, and capacity.
- `qualification_results`: future AI score, category, reasoning, missing information, and next action.
- `email_drafts`: future follow-up drafts and review status.
- `workflow_events`: audit trail of workflow actions.

## Safety notes
- The connection is read only from Streamlit Secrets or the environment.
- Unexpected database errors are displayed generically so credentials are not exposed in the UI.
- This phase creates empty tables and does not yet call an AI model or send email.
- Use synthetic/test data until privacy, consent, and production access controls are reviewed.

## Completion checklist
- [ ] Neon project created.
- [ ] Connection string added to Streamlit Secrets.
- [ ] Phase 2 files uploaded to GitHub root.
- [ ] Connection test succeeds.
- [ ] Five tables are created.
- [ ] Counts display zero for new tables.

**Next: Phase 3** adds a functional lead intake form, server-side validation, duplicate checks, and persistent lead creation in Neon.

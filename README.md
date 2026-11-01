# LeadFlow AI — Phase 3

## What Phase 3 adds
- Functional lead intake form with basic validation.
- Duplicate-email detection before creating a lead.
- Persistent lead creation in Neon PostgreSQL.
- Lead reference generation (for example, `LF-261101-A1B2C3`).
- Workflow event logged for each successfully created lead.
- All Leads page connected to Neon, with text search and status filtering.
- Overview metrics and recent leads loaded from the database.
- Database Setup shows all five expected tables and displays record counts as a readable table (not raw JSON).

## Files in this ZIP
Upload and replace these files in the root of your GitHub repository:
- `app.py`
- `database.py`
- `schema.sql`
- `requirements.txt`
- `README.md`

Do not upload the enclosing ZIP folder itself; upload the five files from inside it to the repository root.

## Before deploying
1. Keep your existing Streamlit Community Cloud secret named `NEON_DATABASE_URL`. Never put the connection string in GitHub or share it in chat.
2. Confirm Neon has the five Phase 2 tables. The app's **Database Setup → Create / verify tables** button is safe to run more than once.
3. Ensure Streamlit Community Cloud is deploying from the branch and root directory where `app.py`, `database.py`, and `requirements.txt` are stored.
4. After GitHub commits the files, wait for Streamlit to redeploy.

## Test Phase 3
1. Open **Database Setup** and click **Test database connection**.
2. Click **Refresh database counts**. The count table should show five rows and a total.
3. Open **Lead Intake** and submit a test lead with a valid email and a need description of at least 10 characters.
4. Open **All Leads** and verify the lead appears.
5. Return to **Lead Intake** and submit the same email again. The app should flag it as a possible duplicate and not create a second record.
6. Open **Workflow History** to see the `lead_created` event.

## Important notes
- Use synthetic/test contacts while testing.
- Phase 3 does not call an AI model, assign sales owners, or send emails.
- Duplicate detection uses email address (case-insensitive). It is an application-level check, not a strict unique database constraint, so concurrent simultaneous submissions could theoretically race. A later hardening phase can add a normalized unique constraint.
- Existing leads are not deleted or overwritten by this update.

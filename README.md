# LeadFlow AI — Phase 4

## What Phase 4 adds
Phase 4 builds on Phase 3 and adds CRM-style potential duplicate detection.

- Keeps exact email duplicate detection (case-insensitive); exact matches block a second submission.
- Finds potential matches using multiple signals:
  - very similar contact name,
  - same or very similar company name,
  - same website domain,
  - same non-free business email domain.
- Displays possible matches before saving.
- Requires the user to explicitly confirm that a new prospect is genuinely different before saving when potential matches are found.
- Does not automatically merge, delete, or overwrite any lead.
- Keeps the Phase 3 lead intake, persistent lead listing, search/filter, database counts, and workflow history.

## Files in this ZIP
Upload these five files to the root of your existing GitHub repository, replacing the corresponding files:
- `app.py`
- `database.py`
- `schema.sql`
- `requirements.txt`
- `README.md`

## Deployment steps
1. Download and extract this ZIP.
2. Open your existing LeadFlow AI repository on GitHub.
3. Upload the five files from the extracted folder to the same repository root where the current `app.py` is located.
4. Commit the changes to the branch used by Streamlit Community Cloud.
5. Wait for Streamlit to redeploy.
6. Keep your existing `NEON_DATABASE_URL` in Streamlit Secrets. Do not copy it into GitHub or share it in chat.

No new Python package or new database table is required for Phase 4. The update uses the existing Neon tables and records. Do not delete or reset your Neon database.

## Test Phase 4
1. Open **Lead Intake** and create a synthetic test lead with a unique email, company, and website.
2. Submit the exact same email again. The app should block it as an exact duplicate.
3. Submit a different email but the same contact name and company/website. The app should show a potential match and ask for confirmation.
4. Leave the confirmation unchecked and submit: no record should be created.
5. Tick the confirmation after reviewing the match and submit again: the new lead should be saved as a separate record.
6. Check **All Leads**, **Workflow History**, and **Database Setup**.

## Matching limitations and safety
- Matching is a heuristic, not proof that two records refer to the same person or organization.
- The lookup checks up to the 500 most recent leads and shows at most 10 likely matches.
- Free email domains (for example Gmail and Outlook) are excluded from business-domain matching.
- Potential matches are never merged automatically. A human must review and confirm.
- Phase 4 does not add AI qualification, enrichment, sales-owner assignment, or email sending.

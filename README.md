# LeadFlow AI — Combined Phase 4 Fix + Phase 5

## What is included
- Phase 4 fix: pending lead data and possible matches are kept in Streamlit session state. The confirmation checkbox and separate **Confirm and save lead** button are outside the form-submit branch, so reruns do not discard the pending lead.
- Exact email duplicates are blocked; similar name/company/website/business-email-domain matches require human confirmation.
- Confirmed leads are saved to Neon and create a `lead_created` workflow event.
- Phase 5: Groq AI qualification provides a 0–100 score, fit category, priority, reasoning, missing information, and recommended next action.
- Qualification results and `lead_ai_qualified` workflow events are saved in Neon; lead status and priority are updated.
- Overview, All Leads, AI Qualification, Workflow History, and Database Setup pages.

AI results are advisory and should be reviewed. The app does not send emails or automatically assign leads.

## Deploy via GitHub website
1. Extract the ZIP.
2. Open your existing LeadFlow AI GitHub repository in the browser.
3. Upload/replace `app.py`, `database.py`, `schema.sql`, `requirements.txt`, and `README.md` in the repository root.
4. Commit the changes and wait for Streamlit Community Cloud to redeploy.

## Streamlit Secrets
In Streamlit Community Cloud, open the app's Settings → Secrets and add your own values:
```toml
NEON_DATABASE_URL = "your-Neon-connection-string"
GROQ_API_KEY = "your-Groq-API-key"
GROQ_MODEL = "openai/gpt-oss-120b"
```
`GROQ_MODEL` is optional. Never commit secrets to GitHub or share them in chat.

## Test Phase 4
1. Create a lead with a unique email.
2. Submit another lead with a different email but a similar name, company, website, or business domain.
3. Review the matches, tick the confirmation checkbox, and click **Confirm and save lead**.
4. Verify it appears in All Leads and Workflow History, and the lead count increases in Database Setup.
5. Try the same email again; it should be blocked.

## Test Phase 5
1. Ensure `GROQ_API_KEY` is configured in Streamlit Secrets.
2. Open AI Qualification, select a lead, and click **Qualify selected lead with AI**.
3. Review the result and check Workflow History / Database Setup for the saved qualification.
4. If the API call fails, the app displays an error and does not save a fabricated result.

The app creates the five expected tables if absent. Back up Neon before replacing files if your schema was customized.

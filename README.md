# LeadFlow AI — Phase 1

A browser-deployed Streamlit starter for the LeadFlow AI project.

## Phase 1 includes
- Streamlit application shell
- Sidebar navigation
- Overview dashboard with clearly labelled placeholder metrics
- Placeholder sections for intake, leads, qualification, assignment/follow-up, and workflow history
- No database, AI, or email integration yet

## Important
All displayed lead names, company names, counts, and activity events are synthetic demo placeholders. They are not saved to a database and must not be treated as real CRM data.

## Planned stack
- Python
- Streamlit
- Neon PostgreSQL (Phase 2)
- Groq API (AI qualification and email drafting in later phases)
- LangGraph (workflow orchestration in a later phase)
- GitHub web interface for file management
- Streamlit Community Cloud for deployment

## Run on Streamlit Community Cloud
1. Upload `app.py`, `requirements.txt`, and `README.md` to a GitHub repository.
2. In Streamlit Community Cloud, create a new app and select that repository.
3. Set the main file path to `app.py`.
4. Deploy.

No secrets are required for Phase 1.

## Next phase
Phase 2 will create the Neon PostgreSQL database and establish a secure connection using Streamlit Secrets.

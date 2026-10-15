AI-first web apply agent upgrade

Installs:
- main.py updated to call the observe -> reason -> act web agent for non-Greenhouse employer/ATS pages.
- manual_link.py for testing one link directly.
- src/web_apply_agent.py: central OpenAI-powered browser loop.
- src/page_observer.py: snapshots page text/controls/hrefs into stable refs.
- src/browser_actions.py: executes safe primitive browser actions.
- src/agent_memory.py: event log, failure memory, answer-bank hints.
- src/site_account_store.py: generated external ATS credentials saved to data/site_accounts.json.
- src/safety_policy.py: safety/permission settings.

Your authorized settings are reflected in defaults:
- Create external ATS accounts: yes.
- Save generated passwords locally: yes.
- Accept standard account/data privacy terms: yes.
- Native Handshake auto-submit remains handled by existing Handshake code.
- External ATS final submit stops at review.
- Missing documents stop.
- GPA/other prior answers are read from data/answer_bank.jsonl when present.

Recommended .env keys:
WEB_APPLY_AGENT_ENABLED=true
WEB_APPLY_AGENT_MODEL=gpt-5-mini
EXTERNAL_ACCOUNT_CREATION_ENABLED=true
EXTERNAL_ACCOUNT_ACCEPT_TERMS=true
EXTERNAL_FINAL_SUBMIT_MODE=stop_at_final_review

The agent writes logs/memory to:
data/application_events.jsonl
data/failure_memory.json
data/site_accounts.json

Do not commit data/ or .env.

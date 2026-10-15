Agentic web apply account-gate fix

This update builds on the state-guard version.

Changes:
- SuccessFactors email-verification/body states are classified before URL-only account_gate classification.
- The account handler now tries saved-credential sign-in when a local account already exists.
- The account handler uses a more tolerant SAP/SuccessFactors button click fallback for Create/Continue/Next/Sign in.
- If the account gate has no visible fields or next controls after account creation, the agent stops cleanly with account_gate_needs_review instead of looping.

Install:
  unzip -o ~/Downloads/agentic_web_apply_account_gate_fix.zip -d .
  python -m py_compile main.py manual_link.py src/web_apply_agent.py src/page_observer.py src/browser_actions.py src/agent_memory.py src/site_account_store.py src/safety_policy.py

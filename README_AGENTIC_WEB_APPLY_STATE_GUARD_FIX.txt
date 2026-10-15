Agentic Web Apply State Guard Fix

This update fixes the AI-first web apply agent after the first guarded build.

Changes:
1. account_gate is handled deterministically before the model is called.
   The agent will stay on the current SuccessFactors session/requestParams URL,
   create/sign in with saved local credentials, and continue observing.

2. The model JSON parser is more tolerant of common invalid JSON glitches.

3. Browser click primitives now complete generic split-button Apply menus:
   click Apply -> if URL did not change -> inspect/click revealed Apply menu item.

4. SuccessFactors sign-in shells move to the Create an account form before filling.

Install:
  unzip -o ~/Downloads/agentic_web_apply_state_guard_fix.zip -d .
  python -m py_compile main.py manual_link.py src/web_apply_agent.py src/page_observer.py src/browser_actions.py src/agent_memory.py src/site_account_store.py src/safety_policy.py

Do not install older external_* fix packages after this; they overwrite the agent files.

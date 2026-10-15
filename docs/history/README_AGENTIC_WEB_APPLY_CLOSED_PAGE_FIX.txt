Closed-page recovery fix

This update makes the AI-first web apply agent robust when SuccessFactors/SAP closes or replaces the Playwright target page after sign-in.

Changes:
- run_web_apply_agent switches to the newest live page when the current page closes.
- wait() no longer crashes the whole process on TargetClosedError.
- manual_link.py prints the newest live page URL/title for review.
- main.py falls back to agent_result.url if the original page handle is closed.

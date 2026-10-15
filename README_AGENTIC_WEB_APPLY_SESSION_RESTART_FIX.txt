AI-first web apply agent session-restart fix

This update keeps the agent from following SAP/SuccessFactors marketing links after a SuccessFactors login/session transition.

Changes:
- Detects about:blank, SAP marketing pages, and dead SuccessFactors career?_s.crb error shells.
- Deterministically relaunches the employer job page from observed browser history using saved credentials instead of letting the model click SuccessFactors/SAP marketing links.
- Blocks www.successfactors.com and www.sap.com open_url/click recovery paths because they are not job application flows.
- Stops with session_recovery_needs_review after repeated dead-session recovery attempts rather than looping.

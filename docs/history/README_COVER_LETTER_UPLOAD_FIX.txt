COVER LETTER UPLOAD FIX

Files included:
- documents/COVER LETTER.pdf
- src/profile.py
- src/recovery_agent.py
- src/handshake.py
- main.py

What changed:
- Adds PROFILE['cover_letter'] pointing to documents/COVER LETTER.pdf.
- Adds cover_letter to the recovery agent's safe upload document list.
- If Handshake or another recovery-agent-supported application page clearly asks for a cover letter, the agent can now upload the configured PDF instead of stopping for manual review.
- The agent still will not generate or invent new cover letters, essays, portfolios, signatures, attestations, or CAPTCHA actions.
- Keeps the current batch-50 discovery behavior from the latest v3 fix.

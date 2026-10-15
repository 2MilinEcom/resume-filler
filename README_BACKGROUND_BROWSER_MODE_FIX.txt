BACKGROUND_BROWSER MODE FIX

This update lets the application runner work without stealing focus from your normal laptop work.

Recommended use:

  APPLICATION_TARGET=50   DISCOVERY_MAX_JOBS=120   FAST_BATCH_MODE=true   BACKGROUND_BROWSER=true   python main.py

How it works:

1. If HANDSHAKE_START_URL is not set, a visible setup window opens once.
2. Log in / configure Handshake search / press ENTER in Terminal.
3. The setup window closes.
4. The batch reopens in hidden headless mode using the same ./browser-data profile.
5. Scanning, uploads, and submissions happen without a visible browser stealing focus.

Fully hidden mode:

  HANDSHAKE_START_URL="https://app.joinhandshake.com/...your jobs search url..."   HEADLESS=true   APPLICATION_TARGET=50   DISCOVERY_MAX_JOBS=120   FAST_BATCH_MODE=true   python main.py

Notes:
- If Berkeley/Handshake asks for login, 2FA, or CAPTCHA, run BACKGROUND_BROWSER=true first so you can complete setup visibly.
- Headless mode cannot solve human verification; it will stop/ask when needed.
- This does not use or disturb your everyday Chrome profile; it uses ./browser-data.

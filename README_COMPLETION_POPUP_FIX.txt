Completion popup fix
====================

This patch adds a macOS popup when the background/headless run finishes.

Default behavior:
- COMPLETION_POPUP=true by default.
- When the run finishes or stops with no more selected jobs, macOS shows a modal dialog titled "Resume Filler Finished".
- The message starts with: "This ran!"
- The terminal summary still prints normally.

Run:

  cd "/Users/shopify/Desktop/RESUME FILLER"
  source .venv/bin/activate
  unzip -o ~/Downloads/completion_popup_fix.zip -d .
  python -m py_compile main.py src/handshake.py

  APPLICATION_TARGET=50 \
  DISCOVERY_MAX_JOBS=120 \
  FAST_BATCH_MODE=true \
  BACKGROUND_BROWSER=true \
  python main.py

Disable popup:

  COMPLETION_POPUP=false python main.py

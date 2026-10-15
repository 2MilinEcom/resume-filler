# Handshake Paid Filter Patch

This patch adds a best-effort Handshake UI filter step:

```bash
HANDSHAKE_FILTER_PAID=true
```

When enabled, the bot will:

1. Open the Handshake Jobs page.
2. Enter `HANDSHAKE_QUERY`.
3. Click the Handshake **Filters** button.
4. Select the **Paid** compensation option.
5. Apply/close the filter panel.
6. Collect jobs only after attempting the paid filter.

Recommended command:

```bash
APPLICATION_TARGET=50 \
DISCOVERY_MAX_JOBS=200 \
FAST_BATCH_MODE=true \
BACKGROUND_BROWSER=true \
REVIEW_BROWSER_ON_FINISH=true \
REVIEW_OPEN_ALL_WORKED=true \
REVIEW_MAX_TABS=80 \
HANDSHAKE_QUERY="Remote Marketing Internship" \
HANDSHAKE_FILTER_PAID=true \
HANDSHAKE_SKIP_UNPAID=true \
HANDSHAKE_DRAFT_ONLY=true \
AI_FILL_QUESTIONNAIRES=true \
AI_GENERATE_OTHER_DOCUMENTS=true \
python main.py
```

`HANDSHAKE_SKIP_UNPAID=true` is still recommended as a backup because Handshake can still return unpaid promoted or stale results even after a UI filter is selected.

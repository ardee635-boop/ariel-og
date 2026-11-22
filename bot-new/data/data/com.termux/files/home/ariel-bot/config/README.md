# config/identities.json

The real phone numbers (King, bot, admin, special-egg sender, the legacy-egg allowlist).
Edit this file and redeploy, no need to touch Render's dashboard.

- Read by Python (`engine/core/config.py`) and by Node (`bot/config.js`).
- A Render environment variable with the same name (e.g. `KING_NUMBER`) overrides the file.
- `KING_NUMBER` and `BOT_NUMBER` are required; the bot refuses to start without them.
- This file IS committed so Render gets it. Keep the repo PRIVATE.
  If the repo ever goes public, delete this file's contents and use Render env vars instead.
- Numbers: digits only with country code. `LEGACY_EGG_IDS` entries are full ids (`...@s.whatsapp.net` or `...@lid`).

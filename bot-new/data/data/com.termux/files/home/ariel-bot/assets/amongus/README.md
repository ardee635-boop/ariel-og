# Among Us images

Put **direct image links** in `image_links.json` (no files are stored here).

- `meeting_call` — sent with the meeting-call message, picked by the caller's colour.
- `ejection` — sent with the role-reveal message, picked by the ejected player's colour.
- `lobby` — one picture sent with the `.lobby open` message (group). Blank = text only.
- `tasks_list` — one picture sent with a living player's `.tasks` (DM). Blank = text only.
- `maps` — also sent with the group's game-start message after `.lobby start` (group only, not DMs).
- A colour with no link uses that section's `default`. No link at all = plain text, as before.
- Links must start with `https://` (or `http://`) and point straight at the image file.
- The file is re-read when it changes; no restart needed.
- Override the location with the env var `AMONGUS_IMAGE_LINKS` if you want it elsewhere.

Official Among Us art belongs to Innersloth; check their fan/mod policy before using it.

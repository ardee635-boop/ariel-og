#!/bin/sh
# Run from the ariel-bot folder:  sh cleanup_stale.sh
# Removes leftovers an overlay zip cannot delete. Safe to run more than once.
set -e
find . -name node_modules -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f bot/handler/web_cmds.js.bak bot/media.js.bak
# Empty, mistyped folders from an old extraction (only removed if empty).
for d in ests ngine; do
  [ -d "$d" ] && find "$d" -depth -type d -empty -delete || true
done
echo "cleaned: __pycache__ folders, 2 .bak files, empty ests/ and ngine/ folders"

#!/usr/bin/env bash
# scripts/switch_fork.sh - swap the Baileys fork under the name your code already imports.
#   bash scripts/switch_fork.sh list        show choices + what is installed now
#   bash scripts/switch_fork.sh <name>      switch (backs up package.json first)
#   bash scripts/switch_fork.sh back        restore the original package.json + reinstall
# Then restart the bot and run  .preview all  from another person's phone.
# Git-based choices need:  pkg install git
set -e
cd "$(dirname "$0")/.."

declare -A F=(
  [lia]="npm:@itsliaaa/baileys@0.3.18-final"      # what you have now
  [lia-latest]="npm:@itsliaaa/baileys@latest"     # same author, newest npm
  [lia-git]="github:itsliaaa/baileys"             # same author, newest source (may be newer than npm)
  [official]="7.0.0-rc13"                         # WhiskeySockets, the original
  [veron]="npm:veron-baileys@latest"
  [melody]="npm:@itsmelody/baileys@latest"
  [c4bal]="npm:@c4bal/baileys@latest"
  [pou]="github:pou-code/Baileys"
)

now() { node -e "try{const p=require('./node_modules/@whiskeysockets/baileys/package.json');console.log('installed:',p.name+'@'+p.version)}catch{console.log('installed: nothing yet')}"; }
want=$(node -e "console.log(require('./package.json').dependencies['@whiskeysockets/baileys'])")

case "${1:-list}" in
  list)
    echo "package.json says: $want"; now; echo
    for k in lia lia-latest lia-git official veron melody c4bal pou; do printf "  %-11s %s\n" "$k" "${F[$k]}"; done
    echo; echo "e.g.  bash scripts/switch_fork.sh lia-git"; exit 0 ;;
  back)
    [ -f package.json.forkbak ] || { echo "no backup yet"; exit 1; }
    cp package.json.forkbak package.json ;;
  *)
    spec="${F[$1]}"; [ -n "$spec" ] || { echo "unknown: $1  (try: list)"; exit 1; }
    [ -f package.json.forkbak ] || cp package.json package.json.forkbak
    SPEC="$spec" node -e "const fs=require('fs');const p=JSON.parse(fs.readFileSync('package.json','utf8'));p.dependencies['@whiskeysockets/baileys']=process.env.SPEC;fs.writeFileSync('package.json',JSON.stringify(p,null,2)+'\n')"
    echo "-> package.json now uses: $spec" ;;
esac

rm -rf node_modules/@whiskeysockets package-lock.json
npm install --omit=dev --no-audit --no-fund
now
echo "Restart the bot now."

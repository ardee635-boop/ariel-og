# Preview kit - what to run (Termux)

## 1. Drop the files in
cd ~/ariel-bot
unzip -o ~/storage/downloads/preview-kit.zip
npm install
(restart the bot)

## 2. Test every preview style (do it from a SECOND phone's view)
.preview            list the styles
.preview all        send A-G one after another
.preview d          one style (a b c d e f g)
.preview d <picture link>   test with your own picture

A bare link (old way)      B sendThumbnail (what Ariel uses)   C mini card
D big card                 E ad-reply card (.invite uses it)    F plain link
G photo + caption (always works)

Reading the result: C/D showing on the other phone = cards work, keep them.
E showing only on YOUR phone = the ad-reply style is the broken one (.invite should switch to D).
Nothing shows for A/B/F = link-preview-js / fork problem.

## 3. Host the pictures on GitHub
node scripts/host_images.mjs            dry run - lists everything
node scripts/host_images.mjs --write --push
(repo must be public) then: .preview d <the raw link it prints>

## 4. Try other Baileys forks
bash scripts/switch_fork.sh list
bash scripts/switch_fork.sh lia-git     (newest source of your current fork - try this first)
bash scripts/switch_fork.sh official
bash scripts/switch_fork.sh back        (undo)
Restart the bot after each switch, then .preview all.

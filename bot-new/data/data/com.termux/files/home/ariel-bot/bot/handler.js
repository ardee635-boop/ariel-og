// handler.js - entry point for every WhatsApp message.
// handleMessage used to be one 2842-line function; it is now a list of steps, one file each in ./handler/,
// run in the original order. A step returns CONTINUE to hand over to the next one; anything else ends handling of the message.
// Locals one step needs from an earlier one (chatJid, senderJid, lower, db, ...) travel in `ctx`.
import { CONTINUE } from './handler/_common.js';
import * as entry from './handler/entry.js';
import * as king_toggles from './handler/king_toggles.js';
import * as group_lists from './handler/group_lists.js';
import * as silent_cmds from './handler/silent_cmds.js';
import * as silent_watch from './handler/silent_watch.js';
import * as gates from './handler/gates.js';
import * as lang from './handler/lang.js';
import * as wcg from './handler/wcg.js';
import * as group_admin from './handler/group_admin.js';
import * as dev_cmds from './handler/dev_cmds.js';
import * as broadcast from './handler/broadcast.js';
import * as fun_cmds from './handler/fun_cmds.js';
import * as media_cmds from './handler/media_cmds.js';
import * as web_cmds from './handler/web_cmds.js';
import * as games from './handler/games.js';
import * as pre_python from './handler/pre_python.js';
import * as afk from './handler/afk.js';
import * as notes from './handler/notes.js';
import * as late_cmds from './handler/late_cmds.js';
import * as python_dispatch from './handler/python_dispatch.js';

const STEPS = [
    entry.run,
    king_toggles.run,
    group_lists.run,
    silent_cmds.run,
    silent_watch.run,
    gates.run,
    lang.run,
    wcg.run,
    group_admin.run,
    dev_cmds.run,
    broadcast.run,
    fun_cmds.run,
    media_cmds.run,
    web_cmds.run,
    games.run,
    pre_python.run,
    afk.run,
    notes.run,
    late_cmds.run,
    python_dispatch.run,
];

export async function handleMessage(sock, msg) {
    const ctx = { sock, msg };
    for (const step of STEPS) {
        const r = await step(ctx);
        if (r !== CONTINUE) return r;
    }
}

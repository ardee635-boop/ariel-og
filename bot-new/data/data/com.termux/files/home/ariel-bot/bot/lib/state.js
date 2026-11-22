import { MINE_WATCH_NUMBER } from './env.js';

// Shared mutable state (was top-level `let` variables in index.js).
// Other modules read/write it as `botState.x`, so ES-module imports never go stale.
export const botState = {
    _pgPool: null,
    _pgReady: null,
    allowedGroups: [],
    ignoredGroups: [],
    groupPools: {},
    silentPoolOn: false,
    chatDmOn: false,
    silentGroups: [],
    silentChatGroups: [],
    activeMines: [],
    mineWatchNumber: MINE_WATCH_NUMBER,
    silentStealConfig: null,
    sleepWindows: [],
    activeSockRef: null,
    pythonProc: null,
    pythonReady: false,
    _reqCounter: 0,
    _groupOrder: null,
    _groupOrderChain: Promise.resolve(),
    currentQR: null,
    currentPairingCode: null,
    _sockStarting: false,
    _currentSock: null,
};

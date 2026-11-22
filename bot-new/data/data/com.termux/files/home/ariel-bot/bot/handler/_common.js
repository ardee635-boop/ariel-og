// bot/handler/_common.js - shared by the handleMessage steps.
// A step returns CONTINUE to fall through to the next step; anything else (including undefined) ends handling of the message.
export const CONTINUE = Symbol('continue');

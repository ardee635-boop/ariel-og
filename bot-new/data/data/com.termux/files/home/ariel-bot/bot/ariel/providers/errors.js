// Every failure from the provider layer is an AIError with a `kind`.
//   timeout | network | server | ratelimit | auth | notfound | bad | empty | budget | breaker | exhausted
export class AIError extends Error {
    constructor(kind, message, { status = null, provider = null, model = null, attempts = null } = {}) {
        super(message);
        this.name = 'AIError';
        this.kind = kind;
        this.status = status;
        this.provider = provider;
        this.model = model;
        this.attempts = attempts;
    }
}

export function kindFromStatus(status) {
    if (status === 429) return 'ratelimit';
    if (status === 408) return 'timeout';
    if (status >= 500) return 'server';
    if (status === 401 || status === 403) return 'auth';
    if (status === 404 || status === 410) return 'notfound';   // dead / retired model
    return 'bad';
}

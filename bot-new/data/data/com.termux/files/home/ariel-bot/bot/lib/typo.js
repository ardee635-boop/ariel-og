// lib/typo.js  (split out of index.js)

// Small edit-distance check so ".take bluzh" against an existing
// "blush" tag gets caught as a likely typo instead of silently
// creating a whole separate, near-duplicate tag. Plain classic
// Levenshtein — good enough for short tag names, no need for a
// dependency here.
function _editDistance(a, b) {
    const dp = Array.from({ length: a.length + 1 }, (_, i) =>
        Array(b.length + 1).fill(0).map((_, j) => (i === 0 ? j : 0))
    );
    for (let i = 0; i <= a.length; i++) dp[i][0] = i;
    for (let i = 1; i <= a.length; i++) {
        for (let j = 1; j <= b.length; j++) {
            dp[i][j] = a[i - 1] === b[j - 1]
                ? dp[i - 1][j - 1]
                : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
        }
    }
    return dp[a.length][b.length];
}

// Returns the closest existing tag to `tag` if it's a likely typo
// (distance 1-2 on a short word), else null. Distance 0 (exact match)
// isn't a typo, it's just "this tag already exists" — handled
// separately as a normal update.
export function _findLikelyTypo(tag, existingTags) {
    let best = null;
    let bestDist = Infinity;
    for (const existing of existingTags) {
        if (existing === tag) continue;
        const dist = _editDistance(tag, existing);
        // Scale the typo threshold to word length — 1 character off
        // on a 4-letter word ("blush"/"bluzh") is significant, but on
        // a much longer tag 2 characters off is still plausibly a typo.
        const threshold = existing.length <= 5 ? 1 : 2;
        if (dist <= threshold && dist < bestDist) {
            best = existing;
            bestDist = dist;
        }
    }
    return best;
}


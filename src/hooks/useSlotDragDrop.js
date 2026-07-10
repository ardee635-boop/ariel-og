import { useState, useCallback } from "react";

/*
  useSlotDragDrop
  ----------------
  Headless drag/swap logic for any grid of "slots" (party, PC, battle
  team picker, trade screen — anything with the shape "N labeled
  positions, each holding zero or one item").

  Not tied to Pokémon specifically beyond the callback shape, and not
  tied to Party/PC specifically — caller supplies its own `zone` id
  per grid (e.g. "party" / "pc") so cross-grid moves are distinguishable
  from same-grid reorders.

  onSwap(from, to) should return a Promise resolving to the new slot
  arrays on success, or throwing/rejecting on failure (server said no).
*/
export function useSlotDragDrop(onSwap) {
  const [dragFrom, setDragFrom] = useState(null); // { zone, idx } | null
  const [dragOverIdx, setDragOverIdx] = useState(null); // { zone, idx } | null
  const [pending, setPending] = useState(false);
  const [flashError, setFlashError] = useState(null);
  const [touchSelected, setTouchSelected] = useState(null); // tap-to-select fallback

  const beginDrag = useCallback((zone, idx, hasMon) => {
    if (!hasMon || pending) return;
    setDragFrom({ zone, idx });
  }, [pending]);

  const dragOverSlot = useCallback((zone, idx) => {
    setDragOverIdx({ zone, idx });
  }, []);

  const clearDragOver = useCallback(() => setDragOverIdx(null), []);

  const endDrag = useCallback(async (zone, idx) => {
    const from = dragFrom;
    setDragFrom(null);
    setDragOverIdx(null);
    if (!from) return;
    if (from.zone === zone && from.idx === idx) return; // dropped on itself

    setPending(true);
    try {
      await onSwap(
        { loc: from.zone, idx: from.idx },
        { loc: zone, idx }
      );
    } catch (e) {
      setFlashError(e?.message || "Swap failed.");
      setTimeout(() => setFlashError(null), 2200);
    } finally {
      setPending(false);
    }
  }, [dragFrom, onSwap]);

  // Touch fallback: first tap selects, second tap on another slot swaps.
  const tapSlot = useCallback(async (zone, idx, hasMon) => {
    if (pending) return;

    setTouchSelected((sel) => {
      if (!sel) {
        return hasMon ? { zone, idx } : null;
      }
      if (sel.zone === zone && sel.idx === idx) {
        return null; // tapped same slot again — deselect
      }
      // Second tap on a different slot — fire the swap, clear selection.
      setPending(true);
      onSwap({ loc: sel.zone, idx: sel.idx }, { loc: zone, idx })
        .catch((e) => {
          setFlashError(e?.message || "Swap failed.");
          setTimeout(() => setFlashError(null), 2200);
        })
        .finally(() => setPending(false));
      return null;
    });
  }, [pending, onSwap]);

  return {
    dragFrom,
    dragOverIdx,
    pending,
    flashError,
    touchSelected,
    beginDrag,
    dragOverSlot,
    clearDragOver,
    endDrag,
    tapSlot,
  };
}

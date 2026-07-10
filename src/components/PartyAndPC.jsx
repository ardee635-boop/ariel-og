import { useState, useCallback } from "react";
import PokemonSlotGrid from "./PokemonSlotGrid";
import { useSlotDragDrop } from "../hooks/useSlotDragDrop";

/*
  PartyAndPC
  -----------
  Owns the real party/pc state and the single shared drag hook, so
  dragging a mon from Party into PC (or back) works across both grids.
  This is the piece that actually talks to /api/player/swap — the
  grid component itself stays backend-agnostic.

  `initialParty` / `initialPc` should come from GET /api/player/me
  (the `party` / `pc` fields), fetched by whatever polls Home.
*/
export default function PartyAndPC({ initialParty, initialPc }) {
  const [party, setParty] = useState(initialParty || []);
  const [pc, setPc] = useState(initialPc || []);

  const handleSwap = useCallback(async (from, to) => {
    const res = await fetch("/api/player/swap", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ from, to }),
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      throw new Error(data.error || "Swap failed.");
    }

    // Server is the source of truth — replace both lists with what it
    // actually persisted, rather than trying to guess the new order
    // ourselves (keeps this correct even if a WhatsApp command changed
    // something in between).
    setParty(data.party || []);
    setPc(data.pc || []);
    return data;
  }, []);

  const drag = useSlotDragDrop(handleSwap);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div
          className="mb-1.5 text-[11px] uppercase tracking-[0.2em] text-cyan-500/80"
          style={{ fontFamily: "'Rajdhani', sans-serif" }}
        >
          Party
        </div>
        <PokemonSlotGrid zone="party" mons={party} slotCount={6} drag={drag} />
      </div>

      <div>
        <div
          className="mb-1.5 text-[11px] uppercase tracking-[0.2em] text-cyan-500/80"
          style={{ fontFamily: "'Rajdhani', sans-serif" }}
        >
          PC Box
        </div>
        <PokemonSlotGrid
          zone="pc"
          mons={pc}
          slotCount={pc.length + 1}
          drag={drag}
        />
      </div>
    </div>
  );
}

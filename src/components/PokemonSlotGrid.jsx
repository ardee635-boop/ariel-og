/*
  PokemonSlotGrid
  ----------------
  Renders one grid of slots (party OR pc — render two instances side by
  side, or stacked, for the full swap experience). Deliberately generic:
  doesn't know about "Home", doesn't assume it's next to a PC grid.

  IMPORTANT: to support dragging *between* two grids (e.g. party <-> pc),
  both instances must share the SAME useSlotDragDrop(onSwap) call from
  a common parent — pass its return value in as `drag`. If you only ever
  need one grid in isolation, you can call the hook locally instead.

  Props:
    zone        "party" | "pc" | any string — must be unique per grid
                instance on the page, used to tag drag payloads
    mons        array of OwnedPokemon-shaped objects (or null gaps —
                though per the backend, party/pc are gapless; this
                component tolerates gaps anyway for safety)
    slotCount   total slots to render (party: 6 fixed; pc: mons.length
                is usually enough, but pass mons.length + 1 to always
                show one open "drop here" slot at the end)
    drag        the object returned by useSlotDragDrop(onSwap), shared
                across sibling grids
    onSlotTap(mon, idx)   optional — open detail panel on a plain click
                          (not drag)
*/
export default function PokemonSlotGrid({
  zone,
  mons,
  slotCount,
  drag,
  onSlotTap,
}) {
  const {
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
  } = drag;

  const total = slotCount ?? mons.length;

  return (
    <div className="w-full">
      <div className="grid grid-cols-2 gap-2">
        {Array.from({ length: total }).map((_, idx) => {
          const mon = mons[idx] || null;
          const isDragSource = dragFrom?.zone === zone && dragFrom?.idx === idx;
          const isDragOver = dragOverIdx?.zone === zone && dragOverIdx?.idx === idx;
          const isTouchSelected = touchSelected?.zone === zone && touchSelected?.idx === idx;

          return (
            <div
              key={idx}
              draggable={!!mon && !pending}
              onDragStart={() => beginDrag(zone, idx, !!mon)}
              onDragOver={(e) => {
                e.preventDefault();
                dragOverSlot(zone, idx);
              }}
              onDragLeave={clearDragOver}
              onDrop={(e) => {
                e.preventDefault();
                endDrag(zone, idx);
              }}
              onDragEnd={clearDragOver}
              onClick={() => {
                if (pending) return;
                tapSlot(zone, idx, !!mon);
                if (mon && onSlotTap) onSlotTap(mon, idx);
              }}
              className={[
                "relative h-[58px] rounded-md border overflow-hidden select-none transition-all duration-150",
                "bg-[#0b1420] border-[#1c2c3d]",
                isDragOver ? "border-cyan-400 shadow-[0_0_0_1px_rgba(34,211,238,0.6)]" : "",
                isDragSource ? "opacity-40" : "",
                isTouchSelected ? "border-cyan-400 shadow-[0_0_10px_rgba(34,211,238,0.35)]" : "",
                mon ? "cursor-grab active:cursor-grabbing" : "cursor-default",
              ].join(" ")}
              style={{
                clipPath: "polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 0 100%)",
              }}
            >
              {mon ? (
                <div className="flex h-full items-center gap-2 px-2">
                  {/* per-type accent bar — no background tint wash */}
                  <span
                    className="h-full w-[3px] shrink-0 rounded-full"
                    style={{ backgroundColor: typeAccent(mon.types?.[0]) }}
                  />
                  <img
                    src={mon.sprite}
                    alt=""
                    className="h-9 w-9 shrink-0 object-contain"
                    draggable={false}
                  />
                  <div className="min-w-0 flex-1">
                    <div
                      className="truncate text-[13px] font-semibold tracking-wide text-cyan-50"
                      style={{ fontFamily: "'Rajdhani', sans-serif" }}
                    >
                      {mon.nickname || mon.name}
                    </div>
                    <div className="text-[10px] text-cyan-500/70">
                      Lv.{mon.level} · {mon.hp}/{mon.max_hp} HP
                    </div>
                  </div>
                </div>
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-0.5 text-cyan-700/60">
                  <span className="grid h-4 w-4 place-items-center rounded-full border border-dashed border-cyan-700/60 text-[10px] leading-none">
                    +
                  </span>
                  <span className="text-[9px] tracking-widest">EMPTY SLOT</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {flashError && (
        <div className="mt-2 rounded border border-red-500/40 bg-red-950/40 px-3 py-1.5 text-[12px] text-red-300">
          {flashError}
        </div>
      )}
    </div>
  );
}

function typeAccent(type) {
  const map = {
    fire: "#f97316", water: "#38bdf8", grass: "#4ade80", electric: "#facc15",
    psychic: "#f472b6", ice: "#67e8f9", dragon: "#818cf8", dark: "#64748b",
    fairy: "#f0abfc", normal: "#a1a1aa", fighting: "#f87171", flying: "#93c5fd",
    poison: "#c084fc", ground: "#d6b98c", rock: "#b8860b", bug: "#a3e635",
    ghost: "#a78bfa", steel: "#94a3b8",
  };
  return map[(type || "").toLowerCase()] || "#22d3ee";
}

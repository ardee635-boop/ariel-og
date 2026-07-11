import { useEffect, useState } from "react";
import PartyAndPC from "../components/PartyAndPC";

/*
  HomePage
  ---------
  Fetches the real player payload from GET /api/player/me and feeds
  party/pc into PartyAndPC. Polls on an interval so a WhatsApp-side
  change (e.g. a potion granted mid-browsing-session) shows up without
  requiring a manual refresh — per the "auto-update while tab is open"
  decision made earlier.
*/
const POLL_INTERVAL_MS = 15000;

export default function HomePage() {
  const [player, setPlayer] = useState(null);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPlayer() {
      try {
        const res = await fetch("/api/player/me", { credentials: "include" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed to load player data.");
        if (!cancelled) {
          setPlayer(data);
          setLoadError(null);
        }
      } catch (e) {
        if (!cancelled) setLoadError(e.message);
      }
    }

    fetchPlayer();
    const interval = setInterval(fetchPlayer, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (loadError) {
    return (
      <div className="p-6 text-center text-red-300">
        {loadError}
      </div>
    );
  }

  if (!player) {
    return (
      <div className="p-6 text-center text-cyan-500/60 tracking-widest text-sm">
        LOADING…
      </div>
    );
  }

  if (player.registered === false) {
    return (
      <div className="p-6 text-center text-cyan-300">
        No trainer data found yet — message the bot on WhatsApp to register first.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl p-4">
      <h1
        className="mb-4 text-lg tracking-widest text-cyan-100"
        style={{ fontFamily: "'Rajdhani', sans-serif" }}
      >
        {player.stats.name} · Lv.{player.stats.level}
      </h1>
      <PartyAndPC initialParty={player.party} initialPc={player.pc} />
    </div>
  );
}

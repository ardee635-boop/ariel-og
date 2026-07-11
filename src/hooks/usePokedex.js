import { useEffect, useState } from "react";

/*
  usePokedex
  -----------
  Fetches the player's caught/seen species names from
  GET /api/player/pokedex, then enriches each one with sprite/genus/
  description/types straight from PokeAPI (species names are already
  lowercase and PokeAPI-compatible — see Player.see_pokemon /
  catch_pokemon in models.py).

  Returns { loading, error, seen, caught } where seen/caught are
  arrays of enriched entries: { name, sprite, genus, description,
  types, status }.
*/

const POKEAPI_BASE = "https://pokeapi.co/api/v2";

async function fetchSpecies(name) {
  const [pokemonRes, speciesRes] = await Promise.all([
    fetch(`${POKEAPI_BASE}/pokemon/${name}`),
    fetch(`${POKEAPI_BASE}/pokemon-species/${name}`),
  ]);
  if (!pokemonRes.ok || !speciesRes.ok) {
    throw new Error(`PokeAPI lookup failed for "${name}"`);
  }
  const pokemon = await pokemonRes.json();
  const species = await speciesRes.json();

  const genus =
    species.genera?.find((g) => g.language.name === "en")?.genus || "";
  const flavorEntry = species.flavor_text_entries?.find(
    (f) => f.language.name === "en"
  );
  const description = flavorEntry
    ? flavorEntry.flavor_text.replace(/[\n\f]/g, " ")
    : "";

  return {
    name: pokemon.name,
    id: pokemon.id,
    sprite:
      pokemon.sprites?.other?.["official-artwork"]?.front_default ||
      pokemon.sprites?.front_default ||
      "",
    types: pokemon.types.map((t) => t.type.name),
    genus,
    description,
  };
}

export function usePokedex() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [seen, setSeen] = useState([]);
  const [caught, setCaught] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch("/api/player/pokedex", {
          credentials: "include",
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed to load Pokédex.");
        if (data.registered === false) {
          if (!cancelled) {
            setSeen([]);
            setCaught([]);
          }
          return;
        }

        const seenNames = data.seen || [];
        const caughtNames = data.caught || [];
        const caughtSet = new Set(caughtNames);

        // Every caught mon has also been seen (see_pokemon runs inside
        // catch_pokemon too), so seenNames already contains caughtNames.
        const enriched = await Promise.all(
          seenNames.map(async (name) => {
            const info = await fetchSpecies(name);
            return {
              ...info,
              status: caughtSet.has(name) ? "caught" : "seen",
            };
          })
        );

        if (cancelled) return;
        setSeen(enriched);
        setCaught(enriched.filter((p) => p.status === "caught"));
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { loading, error, seen, caught };
}

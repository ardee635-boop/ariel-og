import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthProvider } from "./AuthContext";
import RequireAuth from "./RequireAuth";
import HomePage from "./pages/HomePage";

/*
  App
  ----
  Multi-page site per the locked architecture: Home, Leaderboard,
  Pokédex, World/Zones, Rules/Guide. Only HomePage is real so far —
  the rest are stubs to keep routing/navigation honest about what's
  actually built vs. planned, rather than silently 404ing.
*/
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <RequireAuth>
                <HomePage />
              </RequireAuth>
            }
          />
          <Route path="/leaderboard" element={<Stub name="Leaderboard" />} />
          <Route path="/pokedex" element={<Stub name="Pokédex" />} />
          <Route path="/zones" element={<Stub name="World / Zones" />} />
          <Route path="/rules" element={<Stub name="Rules / Guide" />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

function Stub({ name }) {
  return (
    <div className="flex min-h-screen items-center justify-center text-cyan-500/50 tracking-widest text-sm">
      {name.toUpperCase()} — NOT BUILT YET
    </div>
  );
}

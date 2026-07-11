import { createContext, useContext, useEffect, useState } from "react";

/*
  AuthContext
  ------------
  Single source of truth for "am I logged in". On mount, checks
  GET /api/auth/me once — if the session cookie is still valid
  (up to 30 days per issueSessionCookie in index.js), the user is
  considered logged in immediately, no re-entering credentials.
  This IS the "remember me" behavior — it's a consequence of trusting
  the cookie, not a separate feature to build server-side.
*/
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [status, setStatus] = useState("checking"); // "checking" | "authed" | "guest"
  const [user, setUser] = useState(null); // { phone, username } | null
  const [freshLogin, setFreshLogin] = useState(false); // true only right after LoginForm submits successfully

  useEffect(() => {
    let cancelled = false;

    fetch("/api/auth/me", { credentials: "include" })
      .then(async (res) => {
        if (!res.ok) throw new Error("not authed");
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        setUser(data);
        setStatus("authed");
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        setStatus("guest");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = (userData) => {
    setUser(userData);
    setStatus("authed");
    setFreshLogin(true);
  };

  const logout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      // best-effort — clear local state regardless
    }
    setUser(null);
    setStatus("guest");
    setFreshLogin(false);
  };

  return (
    <AuthContext.Provider value={{ status, user, login, logout, freshLogin, clearFreshLogin: () => setFreshLogin(false) }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

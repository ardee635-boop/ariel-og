import LoginForm from "./components/LoginForm";
import { useAuth } from "./AuthContext";

/*
  RequireAuth
  ------------
  Wraps any page that needs a logged-in player. Shows a loading state
  while the initial /api/auth/me check is in flight (so we don't flash
  the login form for a returning user before their cookie's checked),
  the LoginForm if unauthenticated, or the real page content if authed.
*/
export default function RequireAuth({ children }) {
  const { status } = useAuth();

  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center text-cyan-500/60">
        <span className="text-sm tracking-widest">LOADING…</span>
      </div>
    );
  }

  if (status === "guest") {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <LoginForm />
      </div>
    );
  }

  return children;
}

import { useState } from "react";
import { useAuth } from "../AuthContext";

/*
  LoginForm
  ----------
  Real <form> + onSubmit (not just a styled div with an onClick button)
  and correct autocomplete attributes — this is what actually makes
  Chrome/Google offer to save the password. There's no JS API to force
  the save prompt; it only appears when the browser recognizes a
  legitimate password form being submitted successfully.

  Handles both login and signup via a mode toggle, since they hit
  different endpoints but share the same field shape mostly.
*/
export default function LoginForm() {
  const { login } = useAuth();
  const [mode, setMode] = useState("login"); // "login" | "signup"
  const [countryCode, setCountryCode] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    if (mode === "signup" && (!username.trim() || username.length > 50)) {
      setError("Username is required (max 50 characters).");
      return;
    }
    if (password.length < 5) {
      setError("Password must be at least 5 characters.");
      return;
    }
    if (!countryCode.trim() || !phoneNumber.trim()) {
      setError("Phone number is required.");
      return;
    }

    setSubmitting(true);
    try {
      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body =
        mode === "login"
          ? { countryCode, phoneNumber, password }
          : { countryCode, phoneNumber, password, username: username.trim() };

      const res = await fetch(endpoint, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Something went wrong.");
      }

      // Successful submit of a real password <form> is what triggers
      // Chrome's native "Save password?" prompt — nothing else to do here.
      login(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="mx-auto w-full max-w-sm rounded-lg border border-cyan-900/50 bg-[#0b1420] p-6"
      style={{
        clipPath:
          "polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 0 100%)",
      }}
    >
      <h1
        className="mb-5 text-center text-xl font-semibold tracking-widest text-cyan-100"
        style={{ fontFamily: "'Rajdhani', sans-serif" }}
      >
        {mode === "login" ? "Sign In" : "Create Trainer"}
      </h1>

      {mode === "signup" && (
        <label className="mb-3 block">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-cyan-500/80">
            Username
          </span>
          <input
            type="text"
            name="username"
            autoComplete="username"
            maxLength={50}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="w-full rounded border border-cyan-900/60 bg-[#060c14] px-3 py-2 text-cyan-50 outline-none focus:border-cyan-400"
            required
          />
        </label>
      )}

      <div className="mb-3 flex gap-2">
        <label className="w-20 shrink-0">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-cyan-500/80">
            Code
          </span>
          <input
            type="tel"
            name="countryCode"
            autoComplete="tel-country-code"
            placeholder="+1"
            value={countryCode}
            onChange={(e) => setCountryCode(e.target.value)}
            className="w-full rounded border border-cyan-900/60 bg-[#060c14] px-2 py-2 text-cyan-50 outline-none focus:border-cyan-400"
            required
          />
        </label>
        <label className="flex-1">
          <span className="mb-1 block text-[11px] uppercase tracking-wider text-cyan-500/80">
            Phone Number
          </span>
          <input
            type="tel"
            name="phoneNumber"
            autoComplete="tel-national"
            value={phoneNumber}
            onChange={(e) => setPhoneNumber(e.target.value)}
            className="w-full rounded border border-cyan-900/60 bg-[#060c14] px-3 py-2 text-cyan-50 outline-none focus:border-cyan-400"
            required
          />
        </label>
      </div>

      <label className="mb-4 block">
        <span className="mb-1 block text-[11px] uppercase tracking-wider text-cyan-500/80">
          Password
        </span>
        <input
          type="password"
          name="password"
          autoComplete={mode === "login" ? "current-password" : "new-password"}
          minLength={5}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded border border-cyan-900/60 bg-[#060c14] px-3 py-2 text-cyan-50 outline-none focus:border-cyan-400"
          required
        />
      </label>

      {error && (
        <div className="mb-4 rounded border border-red-500/40 bg-red-950/40 px-3 py-2 text-[13px] text-red-300">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded bg-cyan-500/90 px-4 py-2 font-semibold tracking-wide text-[#04101c] transition hover:bg-cyan-400 disabled:opacity-50"
        style={{ fontFamily: "'Rajdhani', sans-serif" }}
      >
        {submitting ? "..." : mode === "login" ? "Sign In" : "Create Trainer"}
      </button>

      <button
        type="button"
        onClick={() => {
          setMode(mode === "login" ? "signup" : "login");
          setError(null);
        }}
        className="mt-3 w-full text-center text-[12px] text-cyan-500/70 hover:text-cyan-300"
      >
        {mode === "login" ? "New here? Create a trainer" : "Already have an account? Sign in"}
      </button>
    </form>
  );
}

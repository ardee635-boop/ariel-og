import { useState } from "react";
import { AuthProvider, useAuth } from "./AuthContext";
import RequireAuth from "./RequireAuth";
import TransitionScene from "./components/TransitionScene";
import IntroScene from "./components/IntroScene";
import HomePage from "./pages/HomePage";

/*
  Post-login sequence, matching the original vanilla flow exactly:
  Login (handled by RequireAuth/LoginForm) -> boot Transition -> one-time
  Intro (lore) -> Home. Every fresh login replays transition+intro, same
  as the original (no persisted "seen intro" flag there either).

  "stage" tracks where we are in that sequence for an already-authed
  session. A page reload lands straight on Home (status starts as
  "checking" then "authed" without ever calling AuthContext.login()),
  matching how the original only ran the boot sequence right after a
  successful login POST, not on every page load.
*/
function PostLoginFlow() {
  const { freshLogin, clearFreshLogin } = useAuth();
  const [stage, setStage] = useState(freshLogin ? "transition" : "home");

  if (stage === "transition") {
    return (
      <TransitionScene
        onDone={() => {
          setStage("intro");
        }}
      />
    );
  }
  if (stage === "intro") {
    return (
      <IntroScene
        onEnter={() => {
          clearFreshLogin();
          setStage("home");
        }}
      />
    );
  }
  return <HomePage />;
}

export default function App() {
  return (
    <AuthProvider>
      <RequireAuth>
        <PostLoginFlow />
      </RequireAuth>
    </AuthProvider>
  );
}

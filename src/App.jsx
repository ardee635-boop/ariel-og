import { AuthProvider } from "./AuthContext";
import RequireAuth from "./RequireAuth";
import HomePage from "./pages/HomePage";

export default function App() {
  return (
    <AuthProvider>
      <RequireAuth>
        <HomePage />
      </RequireAuth>
    </AuthProvider>
  );
}

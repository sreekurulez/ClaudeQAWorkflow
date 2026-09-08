// AuthContext — minimal in-memory auth state via useContext/useState.
// No real JWT validation; the token is stored in state and cleared on logout.
// This mirrors the server's in-memory auth (no session persistence across restarts).
import React, { createContext, useContext, useState } from "react";

interface AuthState {
  token: string | null;
  email: string | null;
}

interface AuthContextValue {
  auth: AuthState;
  login: (email: string, token: string) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [auth, setAuth] = useState<AuthState>({ token: null, email: null });

  const login = (email: string, token: string) => {
    setAuth({ token, email });
  };

  const logout = () => {
    setAuth({ token: null, email: null });
  };

  return (
    <AuthContext.Provider
      value={{ auth, login, logout, isAuthenticated: !!auth.token }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

// Centralized auth state: one subscription, one sign-in/out surface.
// Components read auth via useAuth(); nothing else touches the auth provider directly.
//
// This file is deliberately implementation-agnostic — it consumes the AuthProvider
// interface from ./provider, so it is identical whether Firebase or the development mock
// is behind it.

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { authProvider, type AuthUser } from "./provider";

export interface AuthContextValue {
  /** The signed-in user, or null. */
  user: AuthUser | null;
  /** True until the first auth-state event arrives (show a loading screen, not login). */
  initializing: boolean;
  signIn: () => Promise<void>;
  signOutUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    return authProvider.subscribe((nextUser) => {
      setUser(nextUser);
      setInitializing(false);
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      initializing,
      signIn: () => authProvider.signIn(),
      signOutUser: () => authProvider.signOut(),
    }),
    [user, initializing],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return value;
}

// Centralized Firebase auth state: one listener, one sign-in/out surface.
// Components read auth via useAuth(); nothing else touches firebase/auth directly.

import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { firebaseAuth } from "../firebase";

export interface AuthContextValue {
  /** The signed-in Firebase user, or null. */
  user: User | null;
  /** True until the first auth-state event arrives (show a loading screen, not login). */
  initializing: boolean;
  signIn: () => Promise<void>;
  signOutUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [initializing, setInitializing] = useState(true);

  useEffect(() => {
    return onAuthStateChanged(firebaseAuth, (nextUser) => {
      setUser(nextUser);
      setInitializing(false);
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      initializing,
      signIn: async () => {
        // Google sign-in is the documented dev/demo flow (ADR-011: phone-OTP costs are
        // controlled with test numbers and a Google-login fallback).
        await signInWithPopup(firebaseAuth, new GoogleAuthProvider());
      },
      signOutUser: () => signOut(firebaseAuth),
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

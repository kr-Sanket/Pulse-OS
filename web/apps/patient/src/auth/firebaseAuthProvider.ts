// The real implementation: Firebase Auth behind the AuthProvider interface.
//
// This is the only file besides firebase.ts that knows Firebase exists. It maps the SDK's
// User onto our AuthUser so no Firebase type reaches the rest of the app.

import {
  GoogleAuthProvider,
  onAuthStateChanged,
  signInWithPopup,
  signOut,
  type User,
} from "firebase/auth";

import { getFirebaseAuth } from "../firebase";
import type { AuthProvider, AuthUser } from "./provider";

function toAuthUser(user: User): AuthUser {
  return {
    uid: user.uid,
    displayName: user.displayName,
    email: user.email,
    photoURL: user.photoURL,
    getIdToken: (forceRefresh) => user.getIdToken(forceRefresh),
  };
}

export function createFirebaseAuthProvider(): AuthProvider {
  // Eager: a build without configuration must fail here, at startup, as it always has.
  const auth = getFirebaseAuth();

  return {
    mode: "firebase",
    subscribe: (listener) =>
      onAuthStateChanged(auth, (user) => listener(user === null ? null : toAuthUser(user))),
    getCurrentUser: () => {
      const user = auth.currentUser;
      return user === null ? null : toAuthUser(user);
    },
    signIn: async () => {
      // Google sign-in is the documented dev/demo flow (ADR-011: phone-OTP costs are
      // controlled with test numbers and a Google-login fallback).
      await signInWithPopup(auth, new GoogleAuthProvider());
    },
    signOut: () => signOut(auth),
  };
}

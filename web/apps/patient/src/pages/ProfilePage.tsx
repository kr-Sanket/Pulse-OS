import { useEffect, useState } from "react";

import { api } from "../api";
import { useAuth } from "../auth/AuthContext";
import { LoadingScreen } from "../components/LoadingScreen";
import { loadOrRegisterProfile, type ProfileResult } from "../profile/loadProfile";

export function ProfilePage() {
  const { user, signOutUser } = useAuth();
  const [result, setResult] = useState<ProfileResult | null>(null);

  useEffect(() => {
    if (user === null) {
      return; // ProtectedRoute guarantees a user; guard for the sign-out transition.
    }
    let cancelled = false;
    void loadOrRegisterProfile(
      api,
      { displayName: user.displayName, email: user.email },
      async () => {
        await user.getIdToken(true); // force refresh: pick up freshly provisioned claims
      },
    ).then((outcome) => {
      if (!cancelled) {
        setResult(outcome);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (result === null) {
    return <LoadingScreen message="Loading your profile…" />;
  }

  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem" }}>
      <h1>PulseOS — Patient Portal</h1>
      {result.status === "error" ? (
        <p role="alert">{result.message}</p>
      ) : (
        <dl>
          <dt>Health ID</dt>
          <dd>{result.profile.healthId}</dd>
          <dt>Full name</dt>
          <dd>{result.profile.fullName}</dd>
          <dt>Date of birth</dt>
          <dd>{result.profile.dateOfBirth ?? "—"}</dd>
          <dt>Gender</dt>
          <dd>{result.profile.gender ?? "—"}</dd>
          <dt>Registered on</dt>
          <dd>{new Date(result.profile.createdAt).toLocaleDateString()}</dd>
        </dl>
      )}
      <button type="button" onClick={() => void signOutUser()}>
        Sign out
      </button>
    </main>
  );
}

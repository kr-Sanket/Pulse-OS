// The authenticated shell: sidebar + top bar around a routed <Outlet />.
//
// Owns only presentation state — whether the small-screen drawer is open. Authentication
// stays entirely in ProtectedRoute and the shared AuthContext.

import { useState } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { LoadingScreen } from "@pulseos/ui";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { useCurrentUserRole, type CurrentUserRoleState } from "./useCurrentUserRole";

export interface HospitalLayoutProps {
  useRole?: () => CurrentUserRoleState;
}

export function HospitalLayout({ useRole = useCurrentUserRole }: HospitalLayoutProps = {}) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);
  const { role, loading } = useRole();

  if (loading) {
    return <LoadingScreen message="Checking authorization…" />;
  }

  if (role === "SYSTEM_ADMIN") {
    return <Navigate to="/admin" replace />;
  }

  return (
    <div className="bg-background min-h-svh">
      {drawerOpen ? (
        <button
          type="button"
          className="bg-foreground/40 fixed inset-0 z-30 md:hidden"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      ) : null}

      <Sidebar open={drawerOpen} onNavigate={closeDrawer} role={role} />

      {/* This offset MUST equal the sidebar's width in Sidebar.tsx (w-72 / 18rem). */}
      <div className="flex min-h-svh flex-col md:pl-72">
        <TopBar onMenuClick={() => setDrawerOpen(true)} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8 lg:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

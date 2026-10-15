// Dedicated layout for PulseOS System Administrators.
//
// Wraps administrative pages in AdminSidebar + TopBar around an <Outlet />.
// Enforces role-based authorization: shows a loading screen while role verification
// is pending, and fails closed by redirecting any non-SYSTEM_ADMIN user away before
// rendering administrative views.

import { useState } from "react";
import { Navigate, Outlet } from "react-router-dom";

import { LoadingScreen } from "@pulseos/ui";

import { TopBar } from "@/components/layout/TopBar";
import {
  useCurrentUserRole,
  type CurrentUserRoleState,
} from "@/components/layout/useCurrentUserRole";
import { AdminSidebar } from "./components/AdminSidebar";

export interface AdminLayoutProps {
  useRole?: () => CurrentUserRoleState;
}

export function AdminLayout({ useRole = useCurrentUserRole }: AdminLayoutProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);
  const { role, loading } = useRole();

  // 1. Role loading state: do not reveal any administrative UI
  if (loading) {
    return <LoadingScreen message="Verifying administrative access…" />;
  }

  // 2. Fail closed: unauthorized users (hospital admins, doctors, unprovisioned)
  // are redirected to the default portal root.
  if (role !== "SYSTEM_ADMIN") {
    return <Navigate to="/" replace />;
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

      <AdminSidebar open={drawerOpen} onNavigate={closeDrawer} />

      {/* This offset MUST equal the sidebar's width (w-72 / 18rem). */}
      <div className="flex min-h-svh flex-col md:pl-72">
        <TopBar onMenuClick={() => setDrawerOpen(true)} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8 lg:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

// The authenticated shell: sidebar + top bar around a routed <Outlet />.
//
// Owns only presentation state — whether the small-screen drawer is open. Authentication
// stays entirely in ProtectedRoute and AuthContext; this component renders inside the
// guard and decides nothing about it.

import { useState } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function PatientLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeDrawer = () => setDrawerOpen(false);

  return (
    <div className="bg-background min-h-svh">
      {/* Scrim: only rendered while the drawer is open, and only below md. */}
      {drawerOpen ? (
        <button
          type="button"
          className="bg-foreground/40 fixed inset-0 z-30 md:hidden"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      ) : null}

      <Sidebar open={drawerOpen} onNavigate={closeDrawer} />

      {/* The sidebar is fixed, so this wrapper reserves its width as padding rather than
          wrapping it in a grid — that lets the sidebar scroll independently of the page.
          This offset MUST equal the sidebar's width in Sidebar.tsx (w-72 / 18rem); the two
          are a matched pair. Both the top bar and <main> live inside this wrapper, so they
          share one offset by construction and cannot drift apart from each other. */}
      <div className="flex min-h-svh flex-col md:pl-72">
        <TopBar onMenuClick={() => setDrawerOpen(true)} />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-8 md:py-8 lg:py-10">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

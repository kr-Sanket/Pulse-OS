// Active Grants: who currently has access to the patient's records, which grants are close
// to lapsing, and a standing reminder that access is revocable.
//
// Presentation only — everything comes from src/data/grants.ts and nothing here calls the
// API or holds state. Export, View Details and Revoke Access are visual per spec.

import { Download } from "lucide-react";

import { ActiveGrantCard } from "@/components/grants/ActiveGrantCard";
import { ExpiringGrantCard } from "@/components/grants/ExpiringGrantCard";
import { PrivacyReminderCard } from "@/components/grants/PrivacyReminderCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ACTIVE_GRANTS, EXPIRING_SOON_GRANTS } from "@/data/grants";

export function GrantsPage() {
  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Active Grants</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Manage hospitals and healthcare providers that currently have access to your medical
            records.
          </p>
        </div>
        <Button variant="outline" className="gap-2">
          <Download className="size-4" aria-hidden />
          Export
        </Button>
      </div>

      <section aria-labelledby="active-heading" className="space-y-4">
        <div className="flex items-center gap-2.5">
          <h3 id="active-heading" className="text-sm font-semibold">
            Currently Active Grants
          </h3>
          <Badge variant="success">{ACTIVE_GRANTS.length}</Badge>
        </div>
        {ACTIVE_GRANTS.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            No provider currently has access to your records.
          </p>
        ) : (
          <div className="space-y-4">
            {ACTIVE_GRANTS.map((grant) => (
              <ActiveGrantCard key={grant.id} grant={grant} />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="expiring-heading" className="space-y-4">
        <h3 id="expiring-heading" className="text-sm font-semibold">
          Expiring Soon
        </h3>
        {EXPIRING_SOON_GRANTS.length === 0 ? (
          <p className="text-muted-foreground text-sm">No grants are close to expiring.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2">
            {EXPIRING_SOON_GRANTS.map((grant) => (
              <ExpiringGrantCard key={grant.id} grant={grant} />
            ))}
          </div>
        )}
      </section>

      <PrivacyReminderCard />
    </div>
  );
}

// One live grant, spacious enough to answer the four questions the page exists for: who has
// access, why, which categories, and until when.
//
// One card stands for one *approval*, which the API returns as one row per category — the
// grouping happens in grants/view.ts, so this component receives a single view model and
// renders it. Revoke withdraws every row the card represents; View Details is presentational
// (there is no per-grant endpoint).

import { Building2, Eye, ShieldOff } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge, Button, Card, CardContent, Separator } from "@pulseos/ui";

import { PURPOSE_UNAVAILABLE, type GrantGroupView } from "@/grants/view";

export interface ActiveGrantCardProps {
  grant: GrantGroupView;
  /** A withdrawal is in flight for this card. */
  busy: boolean;
  /** Why the last withdrawal from this card failed, if it did. */
  error: string | null;
  onRevoke: () => void;
}

export function ActiveGrantCard({ grant, busy, error, onRevoke }: ActiveGrantCardProps) {
  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Building2} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{grant.hospital}</h3>
            <p className="text-muted-foreground truncate text-sm">{grant.clinician}</p>
          </div>
          <StatusBadge tone={grant.statusTone}>{grant.statusLabel}</StatusBadge>
        </div>

        <Separator />

        <dl className="grid gap-5 sm:grid-cols-2">
          <Detail label="Purpose">
            {grant.purpose === null ? (
              <span className="text-muted-foreground">{PURPOSE_UNAVAILABLE}</span>
            ) : (
              grant.purpose
            )}
          </Detail>
          <Detail label="Shared records">
            <span className="flex flex-wrap gap-1.5">
              {grant.categories.map((category) => (
                <Badge key={category} variant="secondary">
                  {category}
                </Badge>
              ))}
            </span>
          </Detail>
          <Detail label="Granted">{grant.grantedOn}</Detail>
          <Detail label="Expires">{grant.expiresOn}</Detail>
        </dl>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="outline" size="sm" className="justify-center gap-2 sm:w-auto">
            <Eye className="size-4" aria-hidden />
            View Details
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-destructive hover:text-destructive justify-center gap-2 sm:w-auto"
            disabled={busy}
            onClick={onRevoke}
          >
            <ShieldOff className="size-4" aria-hidden />
            {busy ? "Revoking…" : "Revoke Access"}
          </Button>
        </div>

        {error === null ? null : (
          <p role="alert" className="text-destructive text-sm leading-relaxed">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

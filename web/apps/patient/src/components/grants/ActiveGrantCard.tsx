// One live grant, spacious enough to answer the four questions the page exists for: who has
// access, why, which categories, and until when.
//
// View Details and Revoke Access are presentational per spec — the revoke endpoint exists
// (POST /consent-grants/{id}/revoke) but wiring it is a later slice.

import { Building2, Eye, ShieldOff } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { ActiveGrant } from "@/data/grants";

export interface ActiveGrantCardProps {
  grant: ActiveGrant;
}

export function ActiveGrantCard({ grant }: ActiveGrantCardProps) {
  return (
    <Card className="transition-shadow duration-150 hover:shadow-md hover:shadow-black/[0.04]">
      <CardContent className="space-y-5">
        <div className="flex items-start gap-4">
          <IconChip icon={Building2} />
          <div className="min-w-0 flex-1">
            <h3 className="text-foreground text-[15px] font-medium">{grant.hospital}</h3>
            <p className="text-muted-foreground truncate text-sm">{grant.doctor}</p>
          </div>
          <StatusBadge tone="success">Active</StatusBadge>
        </div>

        <Separator />

        <dl className="grid gap-5 sm:grid-cols-2">
          <Detail label="Purpose">{grant.purpose}</Detail>
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
          >
            <ShieldOff className="size-4" aria-hidden />
            Revoke Access
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// "Needs your review": the pending access requests, as tinted tiles with a single CTA.
// The PulseOS equivalent of the v0 dashboard's consent panel.

import { ShieldQuestion } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import type { ReviewRequest } from "@/dashboard/view";

import { SectionCard } from "./SectionCard";
import { StatusBadge } from "./StatusBadge";

export interface ReviewQueueCardProps {
  requests: readonly ReviewRequest[];
  /** How many tiles to show before deferring to the CTA. */
  previewCount?: number;
}

export function ReviewQueueCard({ requests, previewCount = 2 }: ReviewQueueCardProps) {
  return (
    <SectionCard title="Needs your review" icon={ShieldQuestion} contentClassName="space-y-4 pt-1">
      {requests.length === 0 ? (
        <p className="text-muted-foreground py-2 text-sm">Nothing waiting on you.</p>
      ) : (
        <>
          {requests.slice(0, previewCount).map((request) => (
            <div key={request.id} className="border-border/60 bg-muted/40 rounded-xl border p-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-foreground truncate text-sm font-medium">{request.requester}</p>
                {request.urgent ? <StatusBadge tone="destructive">Urgent</StatusBadge> : null}
              </div>
              <p className="text-muted-foreground mt-1.5 line-clamp-2 text-xs leading-relaxed">
                {request.purpose}
              </p>
            </div>
          ))}
          <Button asChild variant="outline" size="sm" className="w-full">
            <Link to="/consent">
              Review {requests.length} {requests.length === 1 ? "request" : "requests"}
            </Link>
          </Button>
        </>
      )}
    </SectionCard>
  );
}

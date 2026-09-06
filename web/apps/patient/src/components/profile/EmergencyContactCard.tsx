// Who to reach if the patient cannot answer for themselves.
//
// PulseOS does not model an emergency contact (docs/DOMAIN_MODEL.md §1), so this card
// states its absence rather than showing a stand-in. The card and its section stay in
// place: the gap is the backend's, and hiding it would hide that.

import { UserRound } from "lucide-react";

import { IconChip } from "@/components/dashboard/IconChip";
import { Card, CardContent } from "@pulseos/ui";

import { EMERGENCY_CONTACT_EMPTY } from "@/profile/view";

export function EmergencyContactCard() {
  return (
    <Card className="h-full [--card-spacing:--spacing(6)]">
      <CardContent className="flex items-start gap-3.5">
        <IconChip icon={UserRound} size="lg" />
        <div className="min-w-0 space-y-1">
          <p className="text-foreground font-medium">{EMERGENCY_CONTACT_EMPTY.title}</p>
          <p className="text-muted-foreground text-sm leading-relaxed">
            {EMERGENCY_CONTACT_EMPTY.body}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

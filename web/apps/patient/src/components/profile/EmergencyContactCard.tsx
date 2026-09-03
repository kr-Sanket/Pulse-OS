// Who to reach if the patient cannot answer for themselves. Mock data — the backend does
// not model an emergency contact yet.

import { UserRound } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { IconChip } from "@/components/dashboard/IconChip";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { EMERGENCY_CONTACT } from "@/data/profile";

export function EmergencyContactCard() {
  const { name, relationship, phone, secondaryPhone } = EMERGENCY_CONTACT;

  return (
    <Card className="h-full [--card-spacing:--spacing(6)]">
      <CardContent className="space-y-5">
        <div className="flex items-center gap-3.5">
          <IconChip icon={UserRound} size="lg" />
          <div className="min-w-0">
            <p className="text-foreground truncate font-medium">{name}</p>
            <p className="text-muted-foreground text-sm">{relationship}</p>
          </div>
        </div>

        <Separator />

        <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
          <Detail label="Phone Number">
            <span className="tabular-nums">{phone}</span>
          </Detail>
          {secondaryPhone === null ? null : (
            <Detail label="Secondary Phone">
              <span className="tabular-nums">{secondaryPhone}</span>
            </Detail>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

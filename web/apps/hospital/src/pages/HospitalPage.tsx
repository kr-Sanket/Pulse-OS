// My Hospital — the placeholder behind the Account navigation entry.
//
// It exists so the sidebar link goes somewhere truthful rather than bouncing off the
// catch-all redirect. The real page reads GET /api/v1/hospitals/me and renders the hospital's
// name, its HID and its PENDING/VERIFIED state; that is the next slice, and it will replace
// this file wholesale rather than grow out of it.

import { Card, CardContent } from "@pulseos/ui";

export function HospitalPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-1.5">
        <h2 className="text-foreground text-2xl font-semibold tracking-tight">My Hospital</h2>
      </div>

      <Card>
        <CardContent>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Your hospital&rsquo;s details are not connected yet. Registration and verification
            status arrive in the next slice.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

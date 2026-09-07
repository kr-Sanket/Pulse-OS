// The trail, in the order the API returned it (newest first).
//
// A list and nothing else: it holds no state, sorts nothing and formats nothing — the views
// arrive fully worded from audit/view.ts, which is also where the decision not to re-sort a
// paginated, accumulating list is written down.

import { AuditEventCard } from "@/audit/components/AuditEventCard";
import type { AuditEventView } from "@/audit/view";

export interface AuditEventListProps {
  events: readonly AuditEventView[];
}

export function AuditEventList({ events }: AuditEventListProps) {
  return (
    <ul className="space-y-3">
      {events.map((event) => (
        <li key={event.id}>
          <AuditEventCard event={event} />
        </li>
      ))}
    </ul>
  );
}

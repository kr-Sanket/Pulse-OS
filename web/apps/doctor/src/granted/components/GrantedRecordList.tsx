// The records a grant covers, in the order the API returned them (newest added first).
//
// A list and nothing else: it holds no state, sorts nothing and formats nothing — the views
// arrive fully worded from granted/view.ts, which is also where the decision *not* to
// re-sort a possibly truncated page is written down.

import { GrantedRecordCard } from "@/granted/components/GrantedRecordCard";
import type { GrantedRecordView } from "@/granted/view";

export interface GrantedRecordListProps {
  records: readonly GrantedRecordView[];
  /** Passed through to each card, which carries it into navigation state for the Back link. */
  patientHealthId: string;
}

export function GrantedRecordList({ records, patientHealthId }: GrantedRecordListProps) {
  return (
    <ul className="space-y-4">
      {records.map((record) => (
        <li key={record.id}>
          <GrantedRecordCard record={record} patientHealthId={patientHealthId} />
        </li>
      ))}
    </ul>
  );
}

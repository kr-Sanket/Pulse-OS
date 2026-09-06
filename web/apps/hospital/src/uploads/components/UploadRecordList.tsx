// This hospital's uploads, in the order the API returned them (newest added first).
//
// A list and nothing else: it holds no state, sorts nothing and formats nothing — the views
// arrive fully worded from uploads/view.ts, which is also where the decision *not* to
// re-sort a possibly truncated page is written down.

import { UploadRecordCard } from "@/uploads/components/UploadRecordCard";
import type { UploadRecordView } from "@/uploads/view";

export interface UploadRecordListProps {
  records: readonly UploadRecordView[];
}

export function UploadRecordList({ records }: UploadRecordListProps) {
  return (
    <ul className="space-y-4">
      {records.map((record) => (
        <li key={record.id}>
          <UploadRecordCard record={record} />
        </li>
      ))}
    </ul>
  );
}

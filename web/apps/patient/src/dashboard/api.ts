// What the dashboard loads, and from where.
//
// Every call delegates to the feature module that already owns that endpoint — records,
// consent, grants, audit — so there is exactly one implementation of each request in the
// app and the dashboard cannot drift from the page it summarises. This file exists to name
// the dashboard's sources in one place and to adapt their arguments; it issues no request
// of its own and defines no error wording.
//
// Six sources, one request each. Widgets that need the same data share a source rather than
// fetching again — see useDashboard.

import type { PulseOSClient } from "@pulseos/api-client";

import { listAuditEvents } from "@/audit/api";
import { listInbox } from "@/consent/api";
import { listGrants } from "@/grants/api";
import type { ApiResult } from "@pulseos/ui";
import { listCategories, type RecordCategory } from "@pulseos/ui";
import { listRecords, type RecordPage } from "@/records/api";

/** Recent records list + the records figure. Unfiltered: the dashboard shows everything. */
export function loadRecords(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<RecordPage>> {
  return listRecords(client, null, signal);
}

/** Review queue + the pending-requests figure. */
export const loadInbox = listInbox;

/** Expiring-grants card + the active-grants figure. */
export const loadGrants = listGrants;

/** Recent-activity list + the latest-activity figure. */
export const loadTrail = listAuditEvents;

/** Category display names for the records, grants and activity widgets. */
export function loadCategories(
  client: PulseOSClient,
  signal: AbortSignal,
): Promise<ApiResult<RecordCategory[]>> {
  return listCategories(client, signal);
}

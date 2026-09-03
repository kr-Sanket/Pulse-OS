// The dashboard's orchestration: six requests, loaded once each, feeding nine widgets.
//
// The rule this file exists to enforce is **one request per endpoint**. Several widgets
// want the same data — the grants call feeds a figure and the expiring-grants card, the
// inbox call feeds a figure and the review queue, the trail feeds a figure and the activity
// list — and each is loaded here exactly once and shared.
//
// The second rule is **independent failure**. Each source is its own resource with its own
// status, so a dashboard whose audit log is unavailable still shows records, requests,
// grants and the patient's Health ID. Nothing here waits on anything else.

import { useCallback, useMemo } from "react";

import { api } from "@/api";
import { useProfile, type ProfileState } from "@/profile/useProfile";
import { categoryLabels } from "@/lib/recordCategories";
import { useApiResource, type Resource } from "@/lib/useApiResource";

import { loadCategories, loadGrants, loadInbox, loadRecords, loadTrail } from "./api";
import {
  summarize,
  toActivityEntries,
  toExpiringGrants,
  toGrantGroups,
  toRecordEntries,
  toReviewRequests,
  type ActivityEntry,
  type DashboardStat,
  type ExpiringGrant,
  type ReviewRequest,
  type StatSource,
} from "./view";

/** What a widget needs to know about its own source, and nothing about anyone else's. */
export interface Section<T> {
  status: "loading" | "ready" | "error";
  message: string | null;
  data: T;
  reload: () => void;
}

export interface Dashboard {
  /** The identity hero: name and Health ID, through the shared profile bootstrap. */
  profile: ProfileState;
  reloadProfile: () => void;
  stats: readonly DashboardStat[];
  recentRecords: Section<readonly ActivityEntry[]>;
  recentActivity: Section<readonly ActivityEntry[]>;
  reviewQueue: Section<readonly ReviewRequest[]>;
  expiringGrants: Section<readonly ExpiringGrant[]>;
}

function section<S, T>(resource: Resource<S>, reload: () => void, data: T): Section<T> {
  return {
    status: resource.status === "idle" ? "loading" : resource.status,
    message: resource.status === "error" ? resource.message : null,
    data,
    reload,
  };
}

function sourceOf<S, T>(
  resource: Resource<S>,
  items: readonly T[],
  truncated: boolean,
): StatSource<T> {
  return {
    status: resource.status === "idle" ? "loading" : resource.status,
    items,
    truncated,
  };
}

export function useDashboard(): Dashboard {
  const { state: profile, reload: reloadProfile } = useProfile();

  const fetchRecords = useCallback((signal: AbortSignal) => loadRecords(api, signal), []);
  const fetchInbox = useCallback((signal: AbortSignal) => loadInbox(api, signal), []);
  const fetchGrants = useCallback((signal: AbortSignal) => loadGrants(api, signal), []);
  const fetchTrail = useCallback((signal: AbortSignal) => loadTrail(api, signal), []);
  const fetchCategories = useCallback((signal: AbortSignal) => loadCategories(api, signal), []);

  const records = useApiResource(fetchRecords);
  const inbox = useApiResource(fetchInbox);
  const grants = useApiResource(fetchGrants);
  const trail = useApiResource(fetchTrail);
  const categories = useApiResource(fetchCategories);

  const recordsResource = records.resource;
  const inboxResource = inbox.resource;
  const grantsResource = grants.resource;
  const trailResource = trail.resource;
  const categoriesResource = categories.resource;

  const labels = useMemo(
    () =>
      categoriesResource.status === "ready"
        ? categoryLabels(categoriesResource.data)
        : new Map<string, string>(),
    [categoriesResource],
  );

  const recordRows = recordsResource.status === "ready" ? recordsResource.data.items : [];
  const requestRows = inboxResource.status === "ready" ? inboxResource.data.items : [];
  const grantRows = grantsResource.status === "ready" ? grantsResource.data.items : [];
  const eventRows = trailResource.status === "ready" ? trailResource.data.items : [];

  // One grouping of the grants page's own shape, shared by the figure and the card.
  const grantGroups = toGrantGroups(grantRows, labels);

  const stats = summarize({
    records: sourceOf(
      recordsResource,
      recordRows,
      recordsResource.status === "ready" && recordsResource.data.nextCursor !== null,
    ),
    requests: sourceOf(
      inboxResource,
      requestRows,
      inboxResource.status === "ready" && inboxResource.data.nextCursor !== null,
    ),
    grants: sourceOf(
      grantsResource,
      grantGroups,
      grantsResource.status === "ready" && grantsResource.data.nextCursor !== null,
    ),
    events: sourceOf(
      trailResource,
      eventRows,
      trailResource.status === "ready" && trailResource.data.nextCursor !== null,
    ),
  });

  return {
    profile,
    reloadProfile,
    stats,
    recentRecords: section(recordsResource, records.reload, toRecordEntries(recordRows)),
    recentActivity: section(trailResource, trail.reload, toActivityEntries(eventRows, labels)),
    reviewQueue: section(inboxResource, inbox.reload, toReviewRequests(requestRows)),
    expiringGrants: section(grantsResource, grants.reload, toExpiringGrants(grantGroups)),
  };
}

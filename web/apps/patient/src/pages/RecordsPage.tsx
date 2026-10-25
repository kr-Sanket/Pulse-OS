// Medical Records: header, search and filter chips, a list of record cards, and a summary
// panel for the selected record on md and up.
//
// Wired to the backend: categories, the listing, per-record detail, presigned downloads and
// locker uploads all go through the generated client (src/api.ts). Three independent
// requests run here — categories, the listing, and the selected record — each through
// useApiResource, which owns their loading/error states and aborts superseded requests.
//
// Sorting, filtering, searching and paging are all the API's: the page holds one page of
// records at a time, so anything decided in the browser could only ever see a slice of the
// patient's history. That used to be the bug — the listing asked for 100 records, searched
// only those, and had no way to reach the rest.
//
// State is the query (category, search, sort), the pages fetched past the first, which
// record the panel shows, and whether the upload dialog is open. Changing any part of the
// query invalidates the cursor, so the appended pages are dropped with it.

import { Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/api";
import { EmptyRecordsState } from "@/components/records/EmptyRecordsState";
import { RecordCard } from "@/components/records/RecordCard";
import { RecordDetailsPanel } from "@/components/records/RecordDetailsPanel";
import { RecordDetailsSkeleton } from "@/components/records/RecordDetailsSkeleton";
import { RecordFilters } from "@/components/records/RecordFilters";
import { RecordListSkeleton } from "@/components/records/RecordListSkeleton";
import { ErrorState } from "@/components/common/ErrorState";
import { HealthCopilotPanel } from "@/components/copilot/HealthCopilotPanel";
import { FhirExportButton } from "@/components/records/FhirExportButton";
import { UploadRecordDialog } from "@/components/records/UploadRecordDialog";
import {
  createDownloadUrl,
  getRecord,
  listCategories,
  listRecords,
  setRecordVisibility,
  type RecordMetadata,
  type RecordSort,
} from "@/records/api";
import { Button, useApiResource } from "@pulseos/ui";
import {
  applyVisibility,
  applyVisibilityTo,
  DEFAULT_SORT,
  hasActiveFilters,
  searchParam,
} from "@/records/view";

/** Long enough that typing a word is one request, short enough to feel immediate. */
const SEARCH_DEBOUNCE_MS = 300;

interface RecordFailure {
  recordId: string;
  message: string;
}

export function RecordsPage() {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<RecordSort>(DEFAULT_SORT);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadFailure, setDownloadFailure] = useState<RecordFailure | null>(null);

  // Visibility changed in this session, keyed by record id and applied over whatever the
  // listing returned. The same device the grants page uses for revocations, for the same
  // reason: refetching the first page to reflect one record would drop every page Load more
  // has appended. Server state wins the moment the listing itself reloads — see below.
  const [visibilityOverrides, setVisibilityOverrides] = useState<ReadonlyMap<string, boolean>>(
    new Map(),
  );
  const [visibilityBusyId, setVisibilityBusyId] = useState<string | null>(null);
  const [visibilityFailure, setVisibilityFailure] = useState<RecordFailure | null>(null);

  // The field updates on every keystroke; the request waits for a pause. Only the settled
  // term reaches the loader, so typing "lipid" is one listing call rather than five.
  const [settledQuery, setSettledQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSettledQuery(query), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  const loadCategories = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const categories = useApiResource(loadCategories);

  const search = searchParam({ category: activeCategory, search: settledQuery, sort });
  const loadRecords = useCallback(
    (signal: AbortSignal) => listRecords(api, { category: activeCategory, search, sort }, signal),
    [activeCategory, search, sort],
  );
  const records = useApiResource(loadRecords);

  // Hoisted: narrowing a `const` survives into the callbacks below, a property access
  // on the hook's return value does not.
  const recordsResource = records.resource;

  // Pages fetched past the first. A cursor addresses a position in one specific sequence,
  // so whenever the first page is refetched — a new query, or a reload after an upload —
  // everything appended under the old cursor stops belonging to this listing.
  const [appended, setAppended] = useState<RecordMetadata[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreFailure, setMoreFailure] = useState<string | null>(null);
  useEffect(() => {
    if (recordsResource.status !== "ready") {
      return;
    }
    setAppended([]);
    setCursor(recordsResource.data.nextCursor);
    setMoreFailure(null);
    // A fresh listing carries the server's own `isHidden`, which is the authority; keeping
    // this session's overlay on top of it could only ever mask a change made elsewhere.
    setVisibilityOverrides(new Map());
    setVisibilityFailure(null);
  }, [recordsResource]);

  const categoryItems = categories.resource.status === "ready" ? categories.resource.data : [];
  const page = recordsResource.status === "ready" ? recordsResource.data : null;
  const visible = applyVisibility(
    page === null ? [] : [...page.items, ...appended],
    visibilityOverrides,
  );

  const filtersActive = hasActiveFilters({ category: activeCategory, search: query, sort });

  function clearFilters(): void {
    setActiveCategory(null);
    setQuery("");
    setSettledQuery("");
    setSort(DEFAULT_SORT);
  }

  async function loadMore(): Promise<void> {
    if (cursor === null || loadingMore) {
      return;
    }
    setLoadingMore(true);
    setMoreFailure(null);
    const result = await listRecords(
      api,
      { category: activeCategory, search, sort, cursor },
      new AbortController().signal,
    );
    setLoadingMore(false);
    if (result.status === "error") {
      setMoreFailure(result.message);
      return;
    }
    setAppended((previous) => [...previous, ...result.data.items]);
    setCursor(result.data.nextCursor);
  }

  // The panel follows the selection while it is still on screen, and otherwise falls back
  // to the top of the list — so filtering or searching never leaves it pointing at nothing.
  const activeId =
    selectedId !== null && visible.some((record) => record.id === selectedId)
      ? selectedId
      : (visible[0]?.id ?? null);

  const loadDetail = useMemo(
    () => (activeId === null ? null : (signal: AbortSignal) => getRecord(api, activeId, signal)),
    [activeId],
  );
  const detail = useApiResource(loadDetail);
  const detailResource = detail.resource;

  async function download(recordId: string): Promise<void> {
    setDownloadingId(recordId);
    setDownloadFailure(null);
    const result = await createDownloadUrl(api, recordId);
    setDownloadingId(null);
    if (result.status === "error") {
      setDownloadFailure({ recordId, message: result.message });
      return;
    }
    // The URL is presigned and short-lived, and the object is served as an attachment, so
    // opening it downloads the file and leaves the portal mounted in this tab.
    const opened = window.open(result.data.url, "_blank", "noopener");
    if (opened === null) {
      setDownloadFailure({
        recordId,
        message: "Your browser blocked the download window. Allow pop-ups and try again.",
      });
    }
  }

  /** One record, seen through this session's visibility overlay — as the list shows it. */
  function withVisibility(record: RecordMetadata): RecordMetadata {
    return applyVisibilityTo(record, visibilityOverrides);
  }

  async function toggleVisibility(record: RecordMetadata): Promise<void> {
    setVisibilityBusyId(record.id);
    setVisibilityFailure(null);
    const result = await setRecordVisibility(api, record.id, !record.isHidden);
    setVisibilityBusyId(null);
    if (result.status === "error") {
      // The record is left exactly as it was; the toggle is idempotent, so pressing it
      // again simply retries.
      setVisibilityFailure({ recordId: record.id, message: result.message });
      return;
    }
    // The state the server confirmed, not the one we asked for — and applied here rather
    // than by reloading, so the panel stays open and the appended pages stay put.
    setVisibilityOverrides((current) => new Map(current).set(record.id, result.data.isHidden));
  }

  function handleUploaded(record: RecordMetadata): void {
    setUploadOpen(false);
    clearFilters();
    setSelectedId(record.id);
    records.reload();
  }

  function handleSelectCitation(recordId: string): void {
    setSelectedId(recordId);
    const element =
      document.getElementById(`record-${recordId}`) ||
      document.querySelector(`[data-record-id="${recordId}"]`);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Medical Records</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            View and manage all of your health records from connected healthcare providers.
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-3">
          <FhirExportButton />
          <Button className="gap-2" onClick={() => setUploadOpen(true)}>
            <Upload className="size-4" aria-hidden />
            Upload Record
          </Button>
        </div>
      </div>

      <RecordFilters
        categories={categoryItems}
        active={activeCategory}
        onSelect={setActiveCategory}
        query={query}
        onQueryChange={setQuery}
        sort={sort}
        onSortChange={setSort}
        canClear={filtersActive}
        onClear={clearFilters}
        loading={categories.resource.status === "loading"}
      />

      <HealthCopilotPanel onSelectCitation={handleSelectCitation} />

      {recordsResource.status === "loading" || recordsResource.status === "idle" ? (
        <RecordListSkeleton />
      ) : recordsResource.status === "error" ? (
        <ErrorState
          title="Could not load your records."
          message={recordsResource.message}
          onRetry={records.reload}
        />
      ) : visible.length === 0 ? (
        <EmptyRecordsState filtered={filtersActive} onUpload={() => setUploadOpen(true)} />
      ) : (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3 lg:gap-7">
          <div className="space-y-4 md:col-span-2">
            {visible.map((record) => (
              <RecordCard
                key={record.id}
                record={record}
                selected={record.id === activeId}
                onSelect={setSelectedId}
              />
            ))}
            {cursor === null ? null : (
              <div className="space-y-2 pt-1">
                <Button
                  variant="outline"
                  className="w-full justify-center"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                >
                  {loadingMore ? "Loading…" : "Load more records"}
                </Button>
                {moreFailure === null ? null : (
                  <p role="alert" className="text-destructive text-xs leading-relaxed">
                    {moreFailure}
                  </p>
                )}
              </div>
            )}
          </div>

          {/* Summary panel: desktop and tablet only, per spec. */}
          <aside className="hidden md:block" aria-label="Record details">
            {detailResource.status === "loading" || detailResource.status === "idle" ? (
              <RecordDetailsSkeleton />
            ) : detailResource.status === "error" ? (
              <ErrorState
                title="Could not load this record."
                message={detailResource.message}
                onRetry={detail.reload}
              />
            ) : (
              <RecordDetailsPanel
                // The panel reads through the same overlay as the list, so a record hidden
                // here flips its own badge and button without a second fetch of the detail.
                record={withVisibility(detailResource.data)}
                onDownload={() => void download(detailResource.data.id)}
                downloading={downloadingId === detailResource.data.id}
                downloadError={
                  downloadFailure?.recordId === detailResource.data.id
                    ? downloadFailure.message
                    : null
                }
                onToggleVisibility={() =>
                  void toggleVisibility(withVisibility(detailResource.data))
                }
                updatingVisibility={visibilityBusyId === detailResource.data.id}
                visibilityError={
                  visibilityFailure?.recordId === detailResource.data.id
                    ? visibilityFailure.message
                    : null
                }
              />
            )}
          </aside>
        </div>
      )}

      <UploadRecordDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        categories={categoryItems}
        onUploaded={handleUploaded}
      />
    </div>
  );
}

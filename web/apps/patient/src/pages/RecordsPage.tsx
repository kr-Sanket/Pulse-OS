// Medical Records: header, search and filter chips, a list of record cards, and a summary
// panel for the selected record on md and up.
//
// Wired to the backend: categories, the listing, per-record detail, presigned downloads and
// locker uploads all go through the generated client (src/api.ts). Three independent
// requests run here — categories, the listing, and the selected record — each through
// useApiResource, which owns their loading/error states and aborts superseded requests.
//
// State is only what the UI has to decide: the active category (a query parameter), the
// search term (client-side, the API has no search), which record the panel shows, and
// whether the upload dialog is open. Nothing is cached beyond this page.

import { Upload } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { api } from "@/api";
import { EmptyRecordsState } from "@/components/records/EmptyRecordsState";
import { RecordCard } from "@/components/records/RecordCard";
import { RecordDetailsPanel } from "@/components/records/RecordDetailsPanel";
import { RecordDetailsSkeleton } from "@/components/records/RecordDetailsSkeleton";
import { RecordFilters } from "@/components/records/RecordFilters";
import { RecordListSkeleton } from "@/components/records/RecordListSkeleton";
import { ErrorState } from "@/components/common/ErrorState";
import { UploadRecordDialog } from "@/components/records/UploadRecordDialog";
import {
  createDownloadUrl,
  getRecord,
  listCategories,
  listRecords,
  type RecordMetadata,
} from "@/records/api";
import { Button, useApiResource } from "@pulseos/ui";
import { matchesQuery } from "@/records/view";

interface DownloadFailure {
  recordId: string;
  message: string;
}

export function RecordsPage() {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadFailure, setDownloadFailure] = useState<DownloadFailure | null>(null);

  const loadCategories = useCallback((signal: AbortSignal) => listCategories(api, signal), []);
  const categories = useApiResource(loadCategories);

  const loadRecords = useCallback(
    (signal: AbortSignal) => listRecords(api, activeCategory, signal),
    [activeCategory],
  );
  const records = useApiResource(loadRecords);

  // Hoisted: narrowing a `const` survives into the callbacks below, a property access
  // on the hook's return value does not.
  const recordsResource = records.resource;

  const categoryItems = categories.resource.status === "ready" ? categories.resource.data : [];
  const page = recordsResource.status === "ready" ? recordsResource.data : null;
  const visible = page === null ? [] : page.items.filter((record) => matchesQuery(record, query));

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

  function handleUploaded(record: RecordMetadata): void {
    setUploadOpen(false);
    setActiveCategory(null);
    setQuery("");
    setSelectedId(record.id);
    records.reload();
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
        <Button className="gap-2" onClick={() => setUploadOpen(true)}>
          <Upload className="size-4" aria-hidden />
          Upload Record
        </Button>
      </div>

      <RecordFilters
        categories={categoryItems}
        active={activeCategory}
        onSelect={setActiveCategory}
        query={query}
        onQueryChange={setQuery}
        loading={categories.resource.status === "loading"}
      />

      {recordsResource.status === "loading" || recordsResource.status === "idle" ? (
        <RecordListSkeleton />
      ) : recordsResource.status === "error" ? (
        <ErrorState
          title="Could not load your records."
          message={recordsResource.message}
          onRetry={records.reload}
        />
      ) : visible.length === 0 ? (
        <EmptyRecordsState
          filtered={page !== null && (page.items.length > 0 || activeCategory !== null)}
          onUpload={() => setUploadOpen(true)}
        />
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
            {page !== null && page.nextCursor !== null ? (
              <p className="text-muted-foreground text-xs">
                Showing your most recent records. Older ones are not listed yet.
              </p>
            ) : null}
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
                record={detailResource.data}
                onDownload={() => void download(detailResource.data.id)}
                downloading={downloadingId === detailResource.data.id}
                downloadError={
                  downloadFailure?.recordId === detailResource.data.id
                    ? downloadFailure.message
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

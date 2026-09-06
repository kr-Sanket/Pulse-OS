// The Uploaded Records screens' state.
//
// Two hooks, because the two screens ask different questions and have different kinds of
// async. `useUploads` is a pure resource — the listing, loaded on arrival, retried from the
// error state — so the shared useApiResource does all of it and this adds only the outcome
// derivation. `useUpload` adds a download, which is an *action*: it happens when an
// administrator presses a button, and its failure belongs beside the button rather than
// replacing a page whose metadata is still perfectly valid.

import { useCallback, useState } from "react";

import {
  canStartDownload,
  downloadOutcome,
  DOWNLOAD_IDLE,
  useApiResource,
  type DownloadState,
} from "@pulseos/ui";

import { api } from "@/api";

import { createDownloadUrl, getUpload, listUploads, MAX_PAGE_SIZE } from "./api";
import { outcomeFor, toRecordDetailView, type RecordDetailView, type UploadsOutcome } from "./view";

export interface UploadsResource {
  status: "loading" | "ready" | "error";
  /** Why the listing failed, when it did. */
  message: string | null;
  /** Null until the listing has landed; two variants so an empty list is never rendered. */
  outcome: UploadsOutcome | null;
  /** How many a page can hold, for the wording that admits the limit. */
  pageSize: number;
  reload: () => void;
}

export function useUploads(): UploadsResource {
  const load = useCallback((signal: AbortSignal) => listUploads(api, signal), []);
  const { resource, reload } = useApiResource(load);

  return {
    status: resource.status === "idle" ? "loading" : resource.status,
    message: resource.status === "error" ? resource.message : null,
    outcome: resource.status === "ready" ? outcomeFor(resource.data) : null,
    pageSize: MAX_PAGE_SIZE,
    reload,
  };
}

export interface UploadResource {
  status: "loading" | "ready" | "error";
  /** Why the record could not be loaded, when it could not. */
  message: string | null;
  /** The record as the page renders it, or null until it has landed. */
  record: RecordDetailView | null;
  download: DownloadState;
  /** No-op while a download is already being prepared. */
  startDownload: () => void;
  reload: () => void;
}

export function useUpload(recordId: string): UploadResource {
  const load = useCallback((signal: AbortSignal) => getUpload(api, recordId, signal), [recordId]);
  const { resource, reload } = useApiResource(load);
  const [download, setDownload] = useState<DownloadState>(DOWNLOAD_IDLE);

  async function run(): Promise<void> {
    setDownload({ kind: "preparing" });
    const result = await createDownloadUrl(api, recordId);
    if (result.status === "error") {
      setDownload({ kind: "failed", message: result.message });
      return;
    }
    // The URL is presigned, short-lived, and served as an attachment, so opening it
    // downloads the file and leaves the portal mounted in this tab.
    const opened = window.open(result.data.url, "_blank", "noopener");
    setDownload(downloadOutcome(opened !== null));
  }

  return {
    status: resource.status === "idle" ? "loading" : resource.status,
    message: resource.status === "error" ? resource.message : null,
    record: resource.status === "ready" ? toRecordDetailView(resource.data) : null,
    download,
    startDownload: () => {
      // The guard is here rather than on the button so a second click cannot slip through
      // between renders: one intention must not become two audited downloads.
      if (canStartDownload(download)) {
        void run();
      }
    },
    reload,
  };
}

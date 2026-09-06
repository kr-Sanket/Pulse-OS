// The record detail screen's state: one record's metadata, and the download in progress.
//
// Two different kinds of async, deliberately not merged. The metadata is a *resource* —
// loaded on arrival, re-run when the id changes, retried from the error state — so it uses
// the shared useApiResource. The download is an *action*: it happens when a clinician
// presses a button, it has no idle-vs-loading ambiguity, and a failure belongs beside the
// button rather than replacing the page.

import { useCallback, useState } from "react";

import { useApiResource } from "@pulseos/ui";

import { api } from "@/api";

import { createDownloadUrl, getRecord } from "./api";
import { canStartDownload, downloadOutcome } from "@pulseos/ui";

import {
  DOWNLOAD_IDLE,
  toRecordDetailView,
  type DownloadState,
  type RecordDetailView,
} from "./view";

export interface RecordResource {
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

export function useRecord(recordId: string): RecordResource {
  const load = useCallback((signal: AbortSignal) => getRecord(api, recordId, signal), [recordId]);
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

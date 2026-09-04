// The one thing a clinician can do with a record they have been granted: take the file.
//
// The button is disabled only while a link is being prepared, never as a way of expressing
// that access is missing — a record the clinician may not read never reaches this page,
// because the metadata fetch above it would have failed first.
//
// A failure appears beside the button rather than replacing the page: the metadata is still
// valid and still worth reading, so a download that could not be prepared must not take the
// record off the screen with it.

import { Download, Loader2, TriangleAlert } from "lucide-react";

import { SectionCard } from "@/components/shell/SectionCard";
import { Button } from "@/components/ui/button";
import type { DownloadState } from "@/record/view";

export interface RecordActionsProps {
  fileName: string;
  state: DownloadState;
  onDownload: () => void;
}

export function RecordActions({ fileName, state, onDownload }: RecordActionsProps) {
  const preparing = state.kind === "preparing";

  return (
    <SectionCard
      title="File"
      icon={Download}
      description="The link is short-lived and issued to you alone. Downloading is recorded on the patient's audit trail."
      contentClassName="space-y-4 pt-1"
    >
      <Button className="gap-2" disabled={preparing} onClick={onDownload}>
        {preparing ? (
          <Loader2 className="size-4 animate-spin" aria-hidden />
        ) : (
          <Download className="size-4" aria-hidden />
        )}
        {preparing ? "Preparing…" : "Download"}
      </Button>

      <p className="text-muted-foreground text-xs break-all">{fileName}</p>

      {state.kind === "failed" ? (
        <p role="alert" className="text-destructive flex items-start gap-2 text-sm leading-relaxed">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {state.message}
        </p>
      ) : null}
    </SectionCard>
  );
}

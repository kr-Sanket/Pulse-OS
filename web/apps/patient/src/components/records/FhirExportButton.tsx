// Downloads the patient's own records as a FHIR R4 JSON Bundle (GET /records/export/fhir).
//
// Self-contained: owns its in-flight flag and its last outcome, so it can sit in the Records
// header and on the Settings page without either page holding export state. The bundle is
// saved as-is — never parsed, logged or previewed here.

import { useRef, useState } from "react";

import { FileJson } from "lucide-react";

import { api } from "@/api";
import { exportFhirBundle } from "@/records/api";
import { saveBlob } from "@/records/saveFile";
import { Button, cn } from "@pulseos/ui";

type ExportOutcome =
  { kind: "idle" } | { kind: "saved"; filename: string } | { kind: "error"; message: string };

interface FhirExportButtonProps {
  variant?: "default" | "outline";
  className?: string;
  /** The idle button text; Settings passes its own wording. */
  label?: string;
}

export function FhirExportButton({
  variant = "outline",
  className,
  label = "Export FHIR (JSON)",
}: FhirExportButtonProps) {
  const [exporting, setExporting] = useState(false);
  const [outcome, setOutcome] = useState<ExportOutcome>({ kind: "idle" });
  // A ref as well as state: two clicks in the same frame both see `exporting === false`.
  const inFlight = useRef(false);

  async function handleExport(): Promise<void> {
    if (inFlight.current) return;
    inFlight.current = true;
    setExporting(true);
    setOutcome({ kind: "idle" });
    try {
      const result = await exportFhirBundle(api);
      if (result.status === "error") {
        setOutcome({ kind: "error", message: result.message });
        return;
      }
      saveBlob(result.data.blob, result.data.filename);
      setOutcome({ kind: "saved", filename: result.data.filename });
    } finally {
      inFlight.current = false;
      setExporting(false);
    }
  }

  return (
    <div className={cn("flex flex-col items-start gap-1.5", className)}>
      <Button
        variant={variant}
        className="gap-2"
        onClick={() => void handleExport()}
        disabled={exporting}
        aria-busy={exporting}
      >
        <FileJson className="size-4" aria-hidden />
        {exporting ? "Preparing export…" : label}
      </Button>
      {outcome.kind === "error" ? (
        <p role="alert" className="text-destructive max-w-xs text-xs leading-relaxed">
          {outcome.message}
        </p>
      ) : null}
      {outcome.kind === "saved" ? (
        <p role="status" className="text-muted-foreground max-w-xs text-xs leading-relaxed">
          Saved {outcome.filename}
        </p>
      ) : null}
    </div>
  );
}

// The Merkle membership proof for one audit entry (GET /audit-logs/{id}/proof).
//
// Fetched only while the dialog is open, and re-verified by the API on every fetch — the
// status shown is the server's verdict for this request, not a cached copy of the list's.
// Keeps two kinds of evidence apart: local Merkle membership (this entry is a leaf of a
// sealed batch) and public-chain anchoring of that batch's commitment (ADR-035), fetched
// separately and only once the proof has loaded.

import { useCallback } from "react";

import { getAuditProof, getBatchAnchor } from "@/audit/api";
import { chainAnchorView, integrityView, proofRows, type ProofRow } from "@/audit/view";
import { api } from "@/api";
import { StatusBadge } from "@/components/dashboard/StatusBadge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  useApiResource,
} from "@pulseos/ui";

export interface AuditProofDialogProps {
  auditLogId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AuditProofDialog({ auditLogId, open, onOpenChange }: AuditProofDialogProps) {
  const load = useCallback(
    (signal: AbortSignal) => getAuditProof(api, auditLogId, signal),
    [auditLogId],
  );
  const { resource } = useApiResource(open ? load : null);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Integrity proof</DialogTitle>
          <DialogDescription>
            This entry&apos;s digest and the path proving it is one leaf of a sealed local Merkle
            batch, followed by whether that batch&apos;s commitment is anchored on a public test
            network. Only the commitment is published — never your records or this entry.
          </DialogDescription>
        </DialogHeader>

        {resource.status === "loading" || resource.status === "idle" ? (
          <p role="status" className="text-muted-foreground text-sm">
            Verifying…
          </p>
        ) : null}

        {resource.status === "error" ? (
          <p role="alert" className="text-destructive text-sm leading-relaxed">
            {resource.message}
          </p>
        ) : null}

        {resource.status === "ready" ? (
          <>
            <ProofBody proof={resource.data} />
            <ChainAnchorSection batchNumber={resource.data.batchNumber} />
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ProofBody({ proof }: { proof: Parameters<typeof proofRows>[0] }) {
  const verdict = integrityView({
    status: proof.status,
    network: "local-merkle-batch",
    reference: null,
    anchoredAt: null,
  });
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <StatusBadge tone={verdict.tone}>{verdict.label}</StatusBadge>
        <p className="text-muted-foreground text-sm leading-relaxed">{verdict.detail}</p>
      </div>
      <Rows rows={proofRows(proof)} />
    </div>
  );
}

function Rows({ rows }: { rows: readonly ProofRow[] }) {
  return (
    <dl className="grid gap-3">
      {rows.map((row) => (
        <div key={row.label} className="grid gap-0.5">
          <dt className="text-muted-foreground text-xs font-medium">{row.label}</dt>
          <dd
            className={
              row.mono
                ? "text-foreground font-mono text-[12px] break-all"
                : "text-foreground text-sm"
            }
          >
            {row.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ChainAnchorSection({ batchNumber }: { batchNumber: number }) {
  const load = useCallback(
    (signal: AbortSignal) => getBatchAnchor(api, batchNumber, signal),
    [batchNumber],
  );
  const { resource } = useApiResource(load);

  return (
    <section aria-label="Public blockchain anchoring" className="space-y-3 border-t pt-4">
      <h3 className="text-foreground text-sm font-semibold">Public blockchain anchoring</h3>
      {resource.status === "loading" || resource.status === "idle" ? (
        <p role="status" className="text-muted-foreground text-sm">
          Checking the blockchain…
        </p>
      ) : null}
      {resource.status === "error" ? (
        <p role="alert" className="text-destructive text-sm leading-relaxed">
          {resource.message}
        </p>
      ) : null}
      {resource.status === "ready" ? (
        <ChainAnchorBody view={chainAnchorView(resource.data)} />
      ) : null}
    </section>
  );
}

function ChainAnchorBody({ view }: { view: ReturnType<typeof chainAnchorView> }) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <StatusBadge tone={view.tone}>{view.label}</StatusBadge>
        <p className="text-muted-foreground text-sm leading-relaxed">{view.detail}</p>
      </div>
      <Rows rows={view.rows} />
      {view.explorerTxUrl || view.explorerContractUrl ? (
        <div className="flex flex-wrap gap-4 text-sm">
          {view.explorerTxUrl ? (
            <a
              href={view.explorerTxUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-4"
            >
              View transaction on block explorer
            </a>
          ) : null}
          {view.explorerContractUrl ? (
            <a
              href={view.explorerContractUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline underline-offset-4"
            >
              View registry contract
            </a>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

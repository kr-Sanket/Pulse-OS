// The Merkle membership proof for one audit entry (GET /audit-logs/{id}/proof).
//
// Fetched only while the dialog is open, and re-verified by the API on every fetch — the
// status shown is the server's verdict for this request, not a cached copy of the list's.
// Says plainly what the proof covers: a local Merkle batch, not a public blockchain.

import { useCallback } from "react";

import { getAuditProof } from "@/audit/api";
import { integrityView, proofRows } from "@/audit/view";
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
            This entry&apos;s digest, and the path proving it is one leaf of a sealed local Merkle
            batch. PulseOS does not publish batches to a public blockchain.
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

        {resource.status === "ready" ? <ProofBody proof={resource.data} /> : null}
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
      <dl className="grid gap-3">
        {proofRows(proof).map((row) => (
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
    </div>
  );
}

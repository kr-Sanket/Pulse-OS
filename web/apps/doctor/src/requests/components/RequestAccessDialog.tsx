// Ask a patient for access to the categories the clinician selected.
//
// Presentational: every rule — what may be sent, what went wrong, whether a submission is in
// flight — is decided by useAccessRequest and arrives as props. This component renders three
// mutually exclusive faces of one dialog: the draft form, the in-flight form, and the
// confirmation. It never calls the API.

import { Check, Send, ShieldCheck } from "lucide-react";
import type { FormEvent } from "react";

import type { RecordCategory } from "@/existence/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { MAX_PURPOSE_LENGTH } from "@/requests/api";
import { purposeRemaining } from "@/requests/view";
import type { SubmitState } from "@/requests/useAccessRequest";

export interface RequestAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  patientHealthId: string;
  /** The categories the clinician ticked, with their display names. */
  categories: readonly RecordCategory[];
  purpose: string;
  onPurposeChange: (purpose: string) => void;
  /** Why the draft cannot be sent, once a send has been attempted. */
  problem: string | null;
  state: SubmitState;
  onSubmit: () => void;
  /** Dismisses the confirmation and clears the draft. */
  onFinish: () => void;
}

export function RequestAccessDialog({
  open,
  onOpenChange,
  patientHealthId,
  categories,
  purpose,
  onPurposeChange,
  problem,
  state,
  onSubmit,
  onFinish,
}: RequestAccessDialogProps) {
  const submitting = state.kind === "submitting";
  const sent = state.kind === "sent";
  const remaining = purposeRemaining(purpose);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton={!submitting}>
        {sent ? (
          <SentConfirmation
            patientHealthId={patientHealthId}
            categories={categories}
            onFinish={onFinish}
          />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Request access</DialogTitle>
              <DialogDescription>
                The patient decides category by category. Nothing is readable until they approve.
              </DialogDescription>
            </DialogHeader>

            <form className="space-y-4" onSubmit={submit}>
              <div className="space-y-2">
                <Label htmlFor="request-patient">Patient</Label>
                <p
                  id="request-patient"
                  className="text-foreground font-mono text-[13px] tracking-tight"
                >
                  {patientHealthId}
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="request-categories">Requesting</Label>
                <div id="request-categories" className="flex flex-wrap gap-1.5">
                  {categories.map((category) => (
                    <Badge key={category.code} variant="secondary">
                      {category.displayName}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="request-purpose">Purpose</Label>
                <Textarea
                  id="request-purpose"
                  value={purpose}
                  onChange={(event) => onPurposeChange(event.target.value)}
                  placeholder="e.g. Cardiology consultation — reviewing recent results before the appointment"
                  rows={3}
                  maxLength={MAX_PURPOSE_LENGTH}
                  disabled={submitting}
                  aria-describedby="request-purpose-hint"
                />
                <p id="request-purpose-hint" className="text-muted-foreground text-xs">
                  The patient reads this when deciding. {remaining} characters left.
                </p>
              </div>

              {problem === null ? null : (
                <p role="alert" className="text-destructive text-sm leading-relaxed">
                  {problem}
                </p>
              )}
              {state.kind === "error" ? (
                <p role="alert" className="text-destructive text-sm leading-relaxed">
                  {state.message}
                </p>
              ) : null}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => onOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" className="gap-2" disabled={submitting}>
                  <Send className="size-4" aria-hidden />
                  {submitting ? "Sending…" : "Send request"}
                </Button>
              </DialogFooter>
            </form>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** What the clinician sees once the API has accepted the request. */
function SentConfirmation({
  patientHealthId,
  categories,
  onFinish,
}: {
  patientHealthId: string;
  categories: readonly RecordCategory[];
  onFinish: () => void;
}) {
  return (
    <>
      <DialogHeader>
        <div className="bg-success/12 text-success flex size-11 items-center justify-center rounded-2xl">
          <Check className="size-5" aria-hidden />
        </div>
        <DialogTitle>Request sent</DialogTitle>
        <DialogDescription>
          <span className="font-mono text-[13px] tracking-tight">{patientHealthId}</span> now has
          your request for {categories.length} {categories.length === 1 ? "kind" : "kinds"} of
          record.
        </DialogDescription>
      </DialogHeader>

      <div role="status" className="border-border/60 bg-muted/40 flex gap-3 rounded-xl border p-4">
        <ShieldCheck className="text-primary mt-0.5 size-4 shrink-0" aria-hidden />
        <p className="text-muted-foreground text-sm leading-relaxed">
          <span className="text-foreground font-medium">
            The patient must approve before any record becomes available.
          </span>{" "}
          They decide category by category, and can withdraw access at any time. You will see
          nothing new until they do.
        </p>
      </div>

      <DialogFooter>
        <Button type="button" onClick={onFinish}>
          Done
        </Button>
      </DialogFooter>
    </>
  );
}

// Nothing on the roster yet — and the one thing that fixes it.
//
// A hospital cannot add a doctor: doctors register themselves against the hospital's HID
// (ADR-015 step 3), so the useful thing to show here is that HID rather than an action that
// does not exist. An unverified hospital cannot take those registrations at all, so it is
// told that instead of being handed an ID that will be refused.

import { Copy, Stethoscope } from "lucide-react";
import { useState } from "react";

import { Button, Card, CardContent } from "@pulseos/ui";

export interface EmptyDoctorsProps {
  hospitalHid: string;
  /** False while the hospital is still PENDING verification. */
  canRegister: boolean;
}

export function EmptyDoctors({ hospitalHid, canRegister }: EmptyDoctorsProps) {
  const [copied, setCopied] = useState(false);

  async function copyHid(): Promise<void> {
    try {
      await navigator.clipboard.writeText(hospitalHid);
      setCopied(true);
    } catch {
      // Clipboard access can be refused outright; the ID is on screen either way, so this
      // needs no error of its own.
      setCopied(false);
    }
  }

  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <Stethoscope className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">No doctors yet</p>
          <p className="text-muted-foreground mx-auto max-w-md text-sm leading-relaxed">
            {canRegister
              ? "Doctors join by registering themselves in the doctor portal with your Hospital ID. Share it with them, and they will appear here awaiting activation."
              : "Your hospital must be verified before doctors can register to it. Once it is, share your Hospital ID and they will appear here."}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="bg-secondary text-foreground rounded-lg px-3 py-1.5 font-mono text-[13px] tracking-tight">
            {hospitalHid}
          </span>
          <Button variant="outline" size="sm" className="gap-2" onClick={() => void copyHid()}>
            <Copy className="size-4" aria-hidden />
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

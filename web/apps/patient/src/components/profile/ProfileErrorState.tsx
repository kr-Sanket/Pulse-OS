// Shown when the profile bootstrap fails — the API refused, registration was rejected, or
// the network is down. The message is the API's own problem detail wherever it sent one.

import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button, Card, CardContent } from "@pulseos/ui";

export interface ProfileErrorStateProps {
  message: string;
  onRetry: () => void;
}

export function ProfileErrorState({ message, onRetry }: ProfileErrorStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-destructive/10 text-destructive flex size-16 items-center justify-center rounded-2xl">
          <TriangleAlert className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">Could not load your profile.</p>
          <p
            className="text-muted-foreground mx-auto max-w-sm text-sm leading-relaxed"
            role="alert"
          >
            {message}
          </p>
        </div>
        <Button variant="outline" size="sm" className="gap-2" onClick={onRetry}>
          <RotateCcw className="size-4" aria-hidden />
          Try Again
        </Button>
      </CardContent>
    </Card>
  );
}

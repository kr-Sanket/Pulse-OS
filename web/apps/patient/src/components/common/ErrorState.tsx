// Shown when a page's data cannot be loaded. Same shape as the empty states so a column
// keeps its rhythm whichever way the load ends.
//
// In common/ rather than in one feature folder: Records, Consent and everything that
// follows fail the same way, and the retry affordance should not be re-invented per page.

import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button, Card, CardContent } from "@pulseos/ui";

export interface ErrorStateProps {
  /** What could not be loaded, as a sentence. */
  title: string;
  /** The API's own problem detail wherever it sent one. */
  message: string;
  onRetry: () => void;
}

export function ErrorState({ title, message, onRetry }: ErrorStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-destructive/10 text-destructive flex size-16 items-center justify-center rounded-2xl">
          <TriangleAlert className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">{title}</p>
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

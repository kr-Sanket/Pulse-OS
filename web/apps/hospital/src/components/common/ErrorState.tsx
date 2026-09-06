// Shown when a request fails. Same shape as the empty states so a column keeps its rhythm
// whichever way the load ends.

import { RotateCcw, TriangleAlert } from "lucide-react";

import { Button, Card, CardContent } from "@pulseos/ui";

export interface ErrorStateProps {
  title: string;
  /** The API's own problem detail wherever it sent one. */
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ title, message, onRetry }: ErrorStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <span className="bg-destructive/10 text-destructive flex size-14 items-center justify-center rounded-2xl">
          <TriangleAlert className="size-6" aria-hidden />
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
        {onRetry === undefined ? null : (
          <Button variant="outline" size="sm" className="gap-2" onClick={onRetry}>
            <RotateCcw className="size-4" aria-hidden />
            Try Again
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

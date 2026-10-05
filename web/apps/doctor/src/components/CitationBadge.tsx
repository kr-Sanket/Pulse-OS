import type { MouseEvent } from "react";
import { FileText } from "lucide-react";

import { cn } from "@pulseos/ui";

export interface CitationBadgeProps {
  citationIndex: number;
  recordId: string;
  categoryCode?: string;
  onClick?: (recordId: string) => void;
  className?: string;
}

/**
 * Compact, clickable citation badge linking an AI statement to its underlying clinical record.
 */
export function CitationBadge({
  citationIndex,
  recordId,
  categoryCode,
  onClick,
  className,
}: CitationBadgeProps) {
  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    onClick?.(recordId);
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors",
        "bg-secondary/70 hover:bg-secondary text-secondary-foreground border border-border/60 hover:border-primary/40",
        "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        className,
      )}
      aria-label={`Citation [${citationIndex}]: ${categoryCode ?? "Record"}`}
      data-citation-index={citationIndex}
      data-record-id={recordId}
    >
      <FileText className="size-3 text-muted-foreground" aria-hidden />
      <span className="font-semibold text-primary">[{citationIndex}]</span>
      {categoryCode ? (
        <span className="text-muted-foreground font-mono text-[11px]">{categoryCode}</span>
      ) : null}
    </button>
  );
}

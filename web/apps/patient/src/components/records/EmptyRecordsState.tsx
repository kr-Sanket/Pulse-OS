// Shown when the list has nothing in it. Renders inside the list column so the page keeps
// its structure.
//
// Two cases, because they call for different advice: the account genuinely holds no
// records, or the current category/search hides them all.

import { FolderOpen, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export interface EmptyRecordsStateProps {
  /** A filter or search term is narrowing the list, rather than the account being empty. */
  filtered?: boolean;
  onUpload: () => void;
}

export function EmptyRecordsState({ filtered = false, onUpload }: EmptyRecordsStateProps) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <FolderOpen className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">
            {filtered ? "No records match this view." : "No medical records found."}
          </p>
          <p className="text-muted-foreground mx-auto max-w-sm text-sm leading-relaxed">
            {filtered
              ? "Try another category, or clear the search to see everything on your account."
              : "Records uploaded by your hospitals will appear here. You can also add reports you received elsewhere to your own locker."}
          </p>
        </div>
        {filtered ? null : (
          <Button variant="outline" size="sm" className="gap-2" onClick={onUpload}>
            <Upload className="size-4" aria-hidden />
            Upload Record
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

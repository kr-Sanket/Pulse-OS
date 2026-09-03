// Shown when there are no records at all. Renders inside the list column so the page
// keeps its structure.

import { FolderOpen, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export function EmptyRecordsState() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <FolderOpen className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">No medical records found.</p>
          <p className="text-muted-foreground mx-auto max-w-sm text-sm leading-relaxed">
            Records uploaded by your hospitals will appear here. You can also add reports you
            received elsewhere to your own locker.
          </p>
        </div>
        <Button variant="outline" size="sm" className="gap-2">
          <Upload className="size-4" aria-hidden />
          Upload Record
        </Button>
      </CardContent>
    </Card>
  );
}

// Nothing uploaded yet — and the one place that changes it.
//
// Distinct from an error: an empty listing is a successful answer, and a hospital that has
// simply not uploaded anything should not be shown a failure. The link points at the upload
// form because that is the only way a record enters this list.

import { FolderOpen, Upload } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, Card, CardContent } from "@pulseos/ui";

export function EmptyUploads() {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
        <span className="bg-secondary text-muted-foreground flex size-16 items-center justify-center rounded-2xl">
          <FolderOpen className="size-7" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <p className="text-foreground text-[15px] font-medium">No uploads yet</p>
          <p className="text-muted-foreground mx-auto max-w-md text-sm leading-relaxed">
            Records your hospital files against a patient&rsquo;s Pulse Health ID appear here. This
            list never includes records uploaded by other hospitals or by patients themselves.
          </p>
        </div>
        <Button asChild variant="outline" size="sm" className="gap-2">
          <Link to="/upload">
            <Upload className="size-4" aria-hidden />
            Upload a record
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

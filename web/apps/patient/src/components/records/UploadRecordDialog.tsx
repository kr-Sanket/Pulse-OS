// Add a document to the patient's own locker (POST /api/v1/records, multipart).
//
// A modal rather than an inline panel so the page layout is untouched. The dialog owns the
// form and the submission — the page only learns the outcome through onUploaded, and uses
// it to refresh the listing and select the new record.
//
// The API takes the patient from the bearer token, so no Health ID is sent: this is always
// a locker upload. Server-side rules (accepted types, size cap, no future service date)
// are mirrored here only as input hints; the backend remains the authority and its message
// is what gets shown when it refuses.

import { Upload } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/api";
import { uploadRecord, type RecordCategory, type RecordMetadata } from "@/records/api";
import { todayIsoDate } from "@/records/view";

/** Mirrors ALLOWED_CONTENT_TYPES in the records service — a file-picker hint, not a check. */
const ACCEPTED_TYPES = "application/pdf,image/jpeg,image/png";

const DESCRIPTION_MAX_LENGTH = 255;

export interface UploadRecordDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: readonly RecordCategory[];
  /** The record the API created, so the page can refresh and select it. */
  onUploaded: (record: RecordMetadata) => void;
}

export function UploadRecordDialog({
  open,
  onOpenChange,
  categories,
  onUploaded,
}: UploadRecordDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [categoryCode, setCategoryCode] = useState<string | undefined>(undefined);
  const [dateOfService, setDateOfService] = useState(todayIsoDate);
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Every opening starts from a clean form, including after a failed attempt.
  useEffect(() => {
    if (open) {
      setFile(null);
      setCategoryCode(undefined);
      setDateOfService(todayIsoDate());
      setDescription("");
      setError(null);
    }
  }, [open]);

  const canUpload = categories.length > 0;

  async function submit(): Promise<void> {
    if (file === null) {
      setError("Choose a file to upload.");
      return;
    }
    if (categoryCode === undefined) {
      setError("Choose the kind of document this is.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const trimmed = description.trim();
    const result = await uploadRecord(api, {
      file,
      categoryCode,
      dateOfService,
      description: trimmed.length === 0 ? null : trimmed,
    });
    setSubmitting(false);
    if (result.status === "error") {
      setError(result.message);
      return;
    }
    onUploaded(result.data);
  }

  return (
    <Dialog
      open={open}
      // An upload in flight cannot be cancelled, so the dialog stays put until it settles.
      onOpenChange={(next) => {
        if (!submitting) {
          onOpenChange(next);
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Upload a record</DialogTitle>
          <DialogDescription>
            Add a report you received elsewhere to your own locker. Only you can see it until you
            grant a doctor access.
          </DialogDescription>
        </DialogHeader>

        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="upload-file">Document</Label>
            <Input
              id="upload-file"
              type="file"
              accept={ACCEPTED_TYPES}
              required
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <p className="text-muted-foreground text-xs">PDF, JPEG or PNG.</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="upload-category">Kind of document</Label>
            <Select value={categoryCode} onValueChange={setCategoryCode}>
              <SelectTrigger id="upload-category" className="w-full">
                <SelectValue placeholder="Choose a category" />
              </SelectTrigger>
              <SelectContent>
                {categories.map((category) => (
                  <SelectItem key={category.code} value={category.code}>
                    {category.displayName}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="upload-date">Date of service</Label>
            <Input
              id="upload-date"
              type="date"
              required
              value={dateOfService}
              max={todayIsoDate()}
              onChange={(event) => setDateOfService(event.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="upload-description">Description (optional)</Label>
            <Input
              id="upload-description"
              value={description}
              maxLength={DESCRIPTION_MAX_LENGTH}
              placeholder="What this document is"
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>

          {error === null ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              {error}
            </p>
          )}
          {canUpload ? null : (
            <p role="alert" className="text-destructive text-sm leading-relaxed">
              Record categories could not be loaded, so uploads are unavailable right now.
            </p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" className="gap-2" disabled={submitting || !canUpload}>
              <Upload className="size-4" aria-hidden />
              {submitting ? "Uploading…" : "Upload"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

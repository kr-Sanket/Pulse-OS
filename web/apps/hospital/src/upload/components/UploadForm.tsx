// The document half of an upload: what is being filed, not who it is for.
//
// The Health ID and the confirmation live in PatientLookupPanel above this form, because an
// upload proceeds against a *confirmed patient* rather than a typed identifier. This form is
// disabled outright until that confirmation exists, so the two cannot get out of step.
//
// Presentational: the draft, its problems and the in-flight state all arrive as props.

import { Upload } from "lucide-react";
import type { FormEvent } from "react";

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  todayIsoDate,
  type RecordCategory,
} from "@pulseos/ui";

import { ACCEPTED_TYPES, MAX_DESCRIPTION_LENGTH } from "@/upload/api";
import { FIELD_LABELS, type UploadDraft, type UploadField } from "@/upload/view";

export interface UploadFormProps {
  draft: UploadDraft;
  problems: Readonly<Partial<Record<UploadField, string>>>;
  categories: readonly RecordCategory[];
  uploading: boolean;
  /** False until a patient is confirmed, or while the hospital cannot upload at all. */
  enabled: boolean;
  /** Why the form is closed, shown in place of the button's usual affordance. */
  blockedReason: string | null;
  /** Why the API refused the last attempt, if it did. */
  error: string | null;
  onFieldChange: <K extends keyof UploadDraft>(field: K, value: UploadDraft[K]) => void;
  onSubmit: () => void;
}

export function UploadForm({
  draft,
  problems,
  categories,
  uploading,
  enabled,
  blockedReason,
  error,
  onFieldChange,
  onSubmit,
}: UploadFormProps) {
  const disabled = uploading || !enabled;

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit();
  }

  return (
    <form className="space-y-5" onSubmit={submit}>
      <div className="space-y-2">
        <Label htmlFor="file">{FIELD_LABELS.file}</Label>
        <Input
          id="file"
          type="file"
          accept={ACCEPTED_TYPES}
          disabled={disabled}
          aria-invalid={problems.file !== undefined}
          aria-describedby="file-hint"
          onChange={(event) => onFieldChange("file", event.target.files?.[0] ?? null)}
        />
        <p id="file-hint" className="text-muted-foreground text-xs">
          PDF, JPEG or PNG.
        </p>
        <FieldProblem problem={problems.file} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="categoryCode">{FIELD_LABELS.categoryCode}</Label>
        <Select
          value={draft.categoryCode ?? undefined}
          disabled={disabled || categories.length === 0}
          onValueChange={(value) => onFieldChange("categoryCode", value)}
        >
          <SelectTrigger id="categoryCode" className="h-10 w-full">
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
        <FieldProblem problem={problems.categoryCode} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="dateOfService">{FIELD_LABELS.dateOfService}</Label>
        <Input
          id="dateOfService"
          type="date"
          value={draft.dateOfService}
          max={todayIsoDate()}
          disabled={disabled}
          aria-invalid={problems.dateOfService !== undefined}
          onChange={(event) => onFieldChange("dateOfService", event.target.value)}
          className="h-10"
        />
        <FieldProblem problem={problems.dateOfService} />
      </div>

      <div className="space-y-2">
        <Label htmlFor="description">
          Description
          <span className="text-muted-foreground font-normal">(optional)</span>
        </Label>
        <Input
          id="description"
          value={draft.description}
          maxLength={MAX_DESCRIPTION_LENGTH}
          placeholder="What this document is"
          disabled={disabled}
          onChange={(event) => onFieldChange("description", event.target.value)}
          className="h-10"
        />
      </div>

      {error === null ? null : (
        <p role="alert" className="text-destructive text-sm leading-relaxed">
          {error}
        </p>
      )}

      <div className="space-y-2">
        <Button type="submit" className="w-full justify-center gap-2" disabled={disabled}>
          <Upload className="size-4" aria-hidden />
          {uploading ? "Uploading…" : "Upload Record"}
        </Button>
        {blockedReason === null ? null : (
          <p className="text-muted-foreground text-center text-xs leading-relaxed">
            {blockedReason}
          </p>
        )}
      </div>
    </form>
  );
}

function FieldProblem({ problem }: { problem: string | undefined }) {
  if (problem === undefined) {
    return null;
  }
  return (
    <p role="alert" className="text-destructive text-xs leading-relaxed">
      {problem}
    </p>
  );
}

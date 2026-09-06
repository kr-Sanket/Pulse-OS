// The five fields the API accepts for a hospital upload, and nothing else.
//
// Presentational: the draft, its problems and the in-flight state all arrive as props. The
// Health ID leads because it is the field that decides whose history the document joins, and
// it carries the standing caution from upload/view.ts.

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

import { ACCEPTED_TYPES, MAX_DESCRIPTION_LENGTH, MAX_HEALTH_ID_LENGTH } from "@/upload/api";
import { FIELD_LABELS, HEALTH_ID_CAUTION, type UploadDraft, type UploadField } from "@/upload/view";

export interface UploadFormProps {
  draft: UploadDraft;
  problems: Readonly<Partial<Record<UploadField, string>>>;
  categories: readonly RecordCategory[];
  uploading: boolean;
  /** False while the hospital is still PENDING verification — the API would answer 409. */
  enabled: boolean;
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
        <Label htmlFor="patientHealthId">{FIELD_LABELS.patientHealthId}</Label>
        <Input
          id="patientHealthId"
          value={draft.patientHealthId}
          onChange={(event) => onFieldChange("patientHealthId", event.target.value)}
          placeholder="PHI-IND-2026-7K3M99X"
          maxLength={MAX_HEALTH_ID_LENGTH}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={problems.patientHealthId !== undefined}
          aria-describedby="patientHealthId-hint"
          className="h-10 font-mono tracking-tight uppercase"
        />
        <p id="patientHealthId-hint" className="text-muted-foreground text-xs leading-relaxed">
          {HEALTH_ID_CAUTION}
        </p>
        <FieldProblem problem={problems.patientHealthId} />
      </div>

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

      <Button type="submit" className="w-full justify-center gap-2" disabled={disabled}>
        <Upload className="size-4" aria-hidden />
        {uploading ? "Uploading…" : "Upload document"}
      </Button>
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

// The Personal Information card in edit mode.
//
// Three inputs, because three fields are editable. Email and Health ID stay in the same
// card as plain text with a "Read-only" note — not as disabled inputs, which look like a
// control that failed rather than a fact that cannot change.
//
// Presentational: every rule it obeys (what is dirty, what is invalid, what to send) is
// decided in profile/view.ts and held by useProfileEditor.

import { Button, Input, Label } from "@pulseos/ui";

import { Detail } from "@/components/common/Detail";
import type { ProfileEditor } from "@/profile/useProfileEditor";
import { GENDER_OPTIONS, MAX_FULL_NAME, type EditableField } from "@/profile/view";
import type { ProfileIdentity } from "@/profile/view";
import type { PatientProfile } from "@/profile/api";

export interface PersonalInfoFormProps {
  profile: PatientProfile;
  identity: ProfileIdentity;
  editor: ProfileEditor;
}

export function PersonalInfoForm({ profile, identity, editor }: PersonalInfoFormProps) {
  const { draft, fieldErrors, saving } = editor;

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        editor.save();
      }}
      noValidate
    >
      <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
        <Field
          field="fullName"
          label="Full Name"
          error={fieldErrors.fullName}
          editor={editor}
          input={
            <Input
              id="fullName"
              value={draft.fullName}
              maxLength={MAX_FULL_NAME}
              autoComplete="name"
              disabled={saving}
              aria-invalid={fieldErrors.fullName !== undefined}
              onChange={(event) => editor.change("fullName", event.target.value)}
            />
          }
        />

        <Field
          field="dateOfBirth"
          label="Date of Birth"
          error={fieldErrors.dateOfBirth}
          editor={editor}
          input={
            <Input
              id="dateOfBirth"
              type="date"
              value={draft.dateOfBirth}
              disabled={saving}
              aria-invalid={fieldErrors.dateOfBirth !== undefined}
              onChange={(event) => editor.change("dateOfBirth", event.target.value)}
            />
          }
        />

        <Field
          field="gender"
          label="Gender"
          error={fieldErrors.gender}
          editor={editor}
          input={
            <select
              id="gender"
              value={draft.gender}
              disabled={saving}
              onChange={(event) => editor.change("gender", event.target.value)}
              className="border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/25 h-9 w-full rounded-lg border px-3 text-sm outline-none focus-visible:ring-[3px] disabled:opacity-50"
            >
              {GENDER_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          }
        />

        {/* Neither of these is editable, and neither is rendered as a disabled input: a
            greyed-out box reads as a control that broke, not as a fact that cannot move. */}
        <ReadOnly label="Email" value={identity.email} note="Managed by your Google account" />
        <ReadOnly
          label="Health ID"
          value={profile.healthId}
          note="Issued once, never changes"
          mono
        />
      </div>

      {editor.formError === null ? null : (
        <p role="alert" className="text-destructive text-sm leading-relaxed">
          {editor.formError}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={saving || !editor.dirty}>
          {saving ? "Saving…" : "Save Changes"}
        </Button>
        <Button type="button" variant="outline" onClick={editor.cancel} disabled={saving}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function Field({
  field,
  label,
  error,
  input,
}: {
  field: EditableField;
  label: string;
  error: string | undefined;
  editor: ProfileEditor;
  input: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={field}>{label}</Label>
      {input}
      {error === undefined ? null : (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}

function ReadOnly({
  label,
  value,
  note,
  mono = false,
}: {
  label: string;
  value: string;
  note: string;
  mono?: boolean;
}) {
  return (
    <Detail label={label}>
      <span className={mono ? "font-mono text-[13px] tracking-tight" : undefined}>{value}</span>
      <span className="text-muted-foreground mt-0.5 block text-xs">Read-only · {note}</span>
    </Detail>
  );
}

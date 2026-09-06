// Multipart bodies for the one shape of request that is not JSON: a file upload.
//
// openapi-fetch serialises bodies as JSON unless a call passes `bodySerializer`. Both upload
// paths — the patient's locker and a hospital's upload for a Health ID — send the same
// multipart shape to the same endpoint, so the serialiser is shared rather than written twice.
//
// Null and undefined fields are dropped rather than sent as the strings "null"/"undefined":
// the API's optional form fields must be *absent* when unset, not present and wrong.

export function toFormData(body: unknown): FormData {
  const form = new FormData();
  for (const [field, value] of Object.entries(body as Record<string, unknown>)) {
    if (value === null || value === undefined) {
      continue;
    }
    form.append(field, value instanceof Blob ? value : String(value));
  }
  return form;
}

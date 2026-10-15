// System Admin page for reviewing and verifying care organizations.
//
// Mounted under /admin/verification behind ProtectedRoute in HospitalLayout.
// Renders the verification queue, enforces SYSTEM_ADMIN access, and handles verification actions.

import { SystemAdminVerificationView } from "@/admin/components/SystemAdminVerificationView";
import { useHospitalVerification } from "@/admin/useHospitalVerification";

export function SystemAdminVerificationPage() {
  const state = useHospitalVerification();

  return <SystemAdminVerificationView state={state} />;
}

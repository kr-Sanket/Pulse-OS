// Mock consent data for the Consent Requests page. Static by design: this slice is
// presentation only, so nothing here calls the API.
//
// The shapes mirror what the consent module already exposes (docs/DOMAIN_MODEL.md §1 — an
// access request carries a requester with hospital context, a purpose, a set of requested
// categories and an expiry; a grant carries the category it covers and when it lapses), so
// wiring GET /api/v1/access-requests/inbox later is a change of source, not of components.

export interface PendingConsentRequest {
  id: string;
  hospital: string;
  doctor: string;
  purpose: string;
  /** Requested record categories, as the patient sees them. */
  categories: readonly string[];
  /** How long access would last if approved, pre-formatted. */
  duration: string;
  /** Relative time since the request arrived, pre-formatted. */
  requestedAgo: string;
}

export interface ApprovedConsent {
  id: string;
  hospital: string;
  purpose: string;
  /** Pre-formatted grant expiry date. */
  expiresOn: string;
}

export const PENDING_REQUESTS: readonly PendingConsentRequest[] = [
  {
    id: "req-2081",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Meera Sharma",
    purpose: "Specialist Consultation",
    categories: ["Blood Reports", "Prescriptions", "Lab Reports"],
    duration: "30 days",
    requestedAgo: "2 hours ago",
  },
  {
    id: "req-2078",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Cardiology referral — reviewing recent results before your appointment",
    categories: ["Lab Reports", "Imaging", "Discharge Summary"],
    duration: "90 days",
    requestedAgo: "Yesterday",
  },
  {
    id: "req-2074",
    hospital: "TMH Jamshedpur",
    doctor: "Dr. Anjali Verma",
    purpose: "Routine follow-up after your last visit",
    categories: ["Prescriptions"],
    duration: "14 days",
    requestedAgo: "3 days ago",
  },
  {
    id: "req-2070",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Priya Nair",
    purpose: "Radiology review ahead of a scheduled scan",
    categories: ["Imaging", "Visit Notes"],
    duration: "30 days",
    requestedAgo: "5 days ago",
  },
];

export const APPROVED_CONSENTS: readonly ApprovedConsent[] = [
  {
    id: "grant-1904",
    hospital: "TMH Jamshedpur",
    purpose: "Diabetes management",
    expiresOn: "12 Nov 2026",
  },
  {
    id: "grant-1888",
    hospital: "CMC Vellore",
    purpose: "Post-discharge follow-up",
    expiresOn: "28 Sep 2026",
  },
  {
    id: "grant-1875",
    hospital: "Apollo Hospitals",
    purpose: "Annual health review",
    expiresOn: "4 Sep 2026",
  },
];

/** Copy for the standing informational card. */
export const CONSENT_GUIDANCE = {
  title: "Consent Information",
  body:
    "Grant access only when necessary. Hospitals will only be able to view the records " +
    "included in your approval, for as long as the approval lasts.",
  points: [
    "Approvals cover the specific record categories listed — nothing else.",
    "You can withdraw access at any time from Active Grants; it takes effect immediately.",
    "Every time a record of yours is opened, it is recorded in your Audit History.",
  ],
} as const;

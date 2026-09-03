// Mock consent-grant data for the Active Grants page. Static by design: this slice is
// presentation only, so nothing here calls the API.
//
// The shapes mirror what the consent module already models (docs/DOMAIN_MODEL.md §1 — a
// grant ties a patient, a grantee clinician and a record category together with the moment
// it came into force and the moment it lapses), so wiring a grants listing later is a
// change of source, not of components.

export interface ActiveGrant {
  id: string;
  hospital: string;
  doctor: string;
  purpose: string;
  /** Record categories this grant covers, as the patient sees them. */
  categories: readonly string[];
  /** Pre-formatted dates; the API returns ISO timestamps. */
  grantedOn: string;
  expiresOn: string;
}

export interface ExpiringSoonGrant {
  id: string;
  hospital: string;
  purpose: string;
  daysRemaining: number;
  expiresOn: string;
}

export const ACTIVE_GRANTS: readonly ActiveGrant[] = [
  {
    id: "grant-2140",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Meera Sharma",
    purpose: "Cardiology Consultation",
    categories: ["Blood Reports", "ECG", "Prescriptions"],
    grantedOn: "15 Aug 2026",
    expiresOn: "15 Sep 2026",
  },
  {
    id: "grant-2133",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Post-discharge follow-up after day-care admission",
    categories: ["Discharge Summary", "Lab Reports"],
    grantedOn: "2 Aug 2026",
    expiresOn: "31 Oct 2026",
  },
  {
    id: "grant-2128",
    hospital: "TMH Jamshedpur",
    doctor: "Dr. Anjali Verma",
    purpose: "Diabetes management and repeat prescriptions",
    categories: ["Blood Reports", "Prescriptions"],
    grantedOn: "12 Jul 2026",
    expiresOn: "12 Nov 2026",
  },
  {
    id: "grant-2121",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Priya Nair",
    purpose: "Radiology review ahead of a scheduled scan",
    categories: ["Imaging", "Visit Notes"],
    grantedOn: "28 Jun 2026",
    expiresOn: "26 Sep 2026",
  },
  {
    id: "grant-2115",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Annual health review",
    categories: ["Lab Reports"],
    grantedOn: "10 Jun 2026",
    expiresOn: "8 Sep 2026",
  },
];

export const EXPIRING_SOON_GRANTS: readonly ExpiringSoonGrant[] = [
  {
    id: "grant-2115",
    hospital: "CMC Vellore",
    purpose: "Annual health review",
    daysRemaining: 6,
    expiresOn: "8 Sep 2026",
  },
  {
    id: "grant-2140",
    hospital: "Apollo Hospitals",
    purpose: "Cardiology Consultation",
    daysRemaining: 13,
    expiresOn: "15 Sep 2026",
  },
];

/** Copy for the standing privacy card. */
export const PRIVACY_REMINDER = {
  title: "Privacy Reminder",
  body:
    "You can revoke access at any time. Once revoked, healthcare providers will " +
    "immediately lose access to the shared records.",
  points: [
    "A grant only ever covers the record categories listed on it.",
    "Access lapses on its own at the expiry date — you do not need to do anything.",
    "Every record a provider opens is written to your Audit History.",
  ],
} as const;

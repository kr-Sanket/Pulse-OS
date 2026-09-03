// Mock audit data for the Audit History page. Static by design: this slice is presentation
// only, so nothing here calls the API.
//
// The shapes mirror what the consent module's append-only trail already records
// (docs/DOMAIN_MODEL.md §1 — actor and the role they held, the action, the subject patient,
// the record or category targeted, and when it happened), so wiring a patient audit-log
// endpoint later is a change of source, not of components.

import { Building2, Clock, Eye, FlaskConical, type LucideIcon } from "lucide-react";

import type { Tone } from "@/components/dashboard/StatusBadge";

/** The actions a patient sees in their trail. */
export type AuditAction = "Viewed" | "Downloaded" | "Shared" | "Verified";

/** Badge tone per action, so the timeline and any future filter agree. */
export const ACTION_TONE: Record<AuditAction, Tone> = {
  Viewed: "info",
  Downloaded: "primary",
  Shared: "warning",
  Verified: "success",
};

export interface AuditEvent {
  id: string;
  hospital: string;
  doctor: string;
  purpose: string;
  /** Record categories touched by this access. */
  categories: readonly string[];
  /** Pre-formatted; the API returns an ISO timestamp. */
  date: string;
  time: string;
  action: AuditAction;
}

export const AUDIT_EVENTS: readonly AuditEvent[] = [
  {
    id: "evt-5120",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Meera Sharma",
    purpose: "Cardiology Consultation",
    categories: ["Blood Reports", "ECG", "Prescriptions"],
    date: "22 Aug 2026",
    time: "10:42 AM",
    action: "Viewed",
  },
  {
    id: "evt-5118",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Meera Sharma",
    purpose: "Cardiology Consultation",
    categories: ["ECG"],
    date: "22 Aug 2026",
    time: "10:45 AM",
    action: "Downloaded",
  },
  {
    id: "evt-5111",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Post-discharge follow-up",
    categories: ["Discharge Summary", "Lab Reports"],
    date: "20 Aug 2026",
    time: "4:18 PM",
    action: "Viewed",
  },
  {
    id: "evt-5104",
    hospital: "TMH Jamshedpur",
    doctor: "Dr. Anjali Verma",
    purpose: "Diabetes management",
    categories: ["Blood Reports"],
    date: "18 Aug 2026",
    time: "9:05 AM",
    action: "Viewed",
  },
  {
    id: "evt-5098",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Referral to radiology",
    categories: ["Imaging"],
    date: "16 Aug 2026",
    time: "2:31 PM",
    action: "Shared",
  },
  {
    id: "evt-5090",
    hospital: "TMH Jamshedpur",
    doctor: "Dr. Anjali Verma",
    purpose: "Repeat prescription review",
    categories: ["Prescriptions"],
    date: "14 Aug 2026",
    time: "11:20 AM",
    action: "Verified",
  },
  {
    id: "evt-5083",
    hospital: "Apollo Hospitals",
    doctor: "Dr. Priya Nair",
    purpose: "Radiology review ahead of a scan",
    categories: ["Imaging", "Visit Notes"],
    date: "11 Aug 2026",
    time: "5:02 PM",
    action: "Viewed",
  },
  {
    id: "evt-5074",
    hospital: "CMC Vellore",
    doctor: "Dr. Thomas George",
    purpose: "Annual health review",
    categories: ["Lab Reports"],
    date: "8 Aug 2026",
    time: "8:47 AM",
    action: "Downloaded",
  },
  {
    id: "evt-5061",
    hospital: "TMH Jamshedpur",
    doctor: "Dr. Anjali Verma",
    purpose: "Routine follow-up",
    categories: ["Blood Reports", "Prescriptions"],
    date: "4 Aug 2026",
    time: "1:15 PM",
    action: "Viewed",
  },
];

/** Summary figures, shaped for StatCard. */
export interface AuditSummaryStat {
  id: string;
  label: string;
  value: string;
  unit?: string;
  note: string;
  tone: Tone;
  icon: LucideIcon;
}

export const AUDIT_SUMMARY: readonly AuditSummaryStat[] = [
  {
    id: "total",
    label: "Total accesses",
    value: "42",
    note: "Since you joined",
    tone: "info",
    icon: Eye,
  },
  {
    id: "hospitals",
    label: "Hospitals involved",
    value: "3",
    note: "TMH, CMC, Apollo",
    tone: "neutral",
    icon: Building2,
  },
  {
    id: "most-accessed",
    label: "Most accessed",
    value: "18",
    unit: "views",
    note: "Blood Reports",
    tone: "primary",
    icon: FlaskConical,
  },
  {
    id: "last-access",
    label: "Last access",
    value: "2",
    unit: "hours ago",
    note: "Apollo Hospitals",
    tone: "success",
    icon: Clock,
  },
];

/** Copy for the standing privacy card. */
export const AUDIT_PRIVACY = {
  title: "Privacy Information",
  body:
    "Every access to your medical records is permanently logged to provide complete " +
    "transparency.",
  points: [
    "Entries are append-only — they can never be edited or deleted, by anyone.",
    "You see the same trail your providers do, including refused attempts.",
    "Revoking a grant in Active Grants stops further access immediately.",
  ],
} as const;

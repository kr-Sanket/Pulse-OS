// Mock dashboard data. Deliberately static: M4's first slice is layout only, so nothing
// here calls the API. When the real endpoints land, these shapes are what the fetch layer
// should return, so the presentation components below need no changes.

import {
  Activity,
  Download,
  FileText,
  FlaskConical,
  IdCard,
  KeyRound,
  Pill,
  ScanLine,
  ShieldCheck,
  StickyNote,
  Upload,
  type LucideIcon,
} from "lucide-react";

export interface DashboardStat {
  id: string;
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
}

export interface QuickAction {
  id: string;
  title: string;
  description: string;
  actionLabel: string;
  to: string;
  icon: LucideIcon;
}

export type ActivityTone =
  "default" | "secondary" | "destructive" | "primary" | "success" | "warning" | "info" | "neutral";

export interface ActivityEntry {
  id: string;
  title: string;
  description: string;
  icon: LucideIcon;
  /** Trailing relative time, when the row has one. */
  timestamp?: string;
  /** Trailing badge, when the row has one. */
  badgeLabel?: string;
  tone?: ActivityTone;
  /** Internal route the row links to, when it is navigable. */
  to?: string;
}

export const DASHBOARD_STATS: readonly DashboardStat[] = [
  {
    id: "records",
    label: "Medical records",
    value: "12",
    hint: "Across 2 hospitals",
    icon: FileText,
  },
  {
    id: "pending-requests",
    label: "Pending requests",
    value: "2",
    hint: "Awaiting your decision",
    icon: ShieldCheck,
  },
  {
    id: "active-grants",
    label: "Active grants",
    value: "3",
    hint: "Expire within 90 days",
    icon: KeyRound,
  },
  {
    id: "recent-access",
    label: "Accesses this month",
    value: "8",
    hint: "All recorded in your audit log",
    icon: Activity,
  },
];

export const QUICK_ACTIONS: readonly QuickAction[] = [
  {
    id: "review-requests",
    title: "Review access requests",
    description: "Decide per category which doctors may read your records.",
    actionLabel: "Open requests",
    to: "/consent",
    icon: ShieldCheck,
  },
  {
    id: "upload-record",
    title: "Add to your locker",
    description: "Upload a report you received outside a partner hospital.",
    actionLabel: "Upload a record",
    to: "/records",
    icon: Upload,
  },
  {
    id: "health-id",
    title: "Your Health ID",
    description: "Show your PulseOS ID at a reception desk.",
    actionLabel: "View profile",
    to: "/profile",
    icon: IdCard,
  },
];

export const RECENT_ACTIVITY: readonly ActivityEntry[] = [
  {
    id: "a1",
    title: "Dr Thomas George viewed CBC",
    description: "CMC Vellore · granted 12 Aug",
    timestamp: "2 hours ago",
    tone: "secondary",
    badgeLabel: "Viewed",
    icon: FileText,
  },
  {
    id: "a2",
    title: "Access request from Apollo Hospitals",
    description: "Requested MRI and Discharge Summary",
    timestamp: "Yesterday",
    tone: "default",
    badgeLabel: "Pending",
    icon: ShieldCheck,
  },
  {
    id: "a3",
    title: "You revoked access to X-Ray",
    description: "Grantee: Dr Anjali Verma · TMH Jamshedpur",
    timestamp: "3 days ago",
    tone: "destructive",
    badgeLabel: "Revoked",
    icon: KeyRound,
  },
  {
    id: "a4",
    title: "Discharge summary downloaded",
    description: "By you · TMH Jamshedpur",
    timestamp: "Last week",
    tone: "secondary",
    badgeLabel: "Downloaded",
    icon: Download,
  },
];

// -- v0 dashboard sections -------------------------------------------------------------
//
// Added for the migrated dashboard layout. Still mock data: nothing here calls the API.

export interface ReviewRequest {
  id: string;
  requester: string;
  purpose: string;
  urgent: boolean;
}

export interface ExpiringGrant {
  id: string;
  grantee: string;
  /** Category and hospital the grant covers. */
  scope: string;
  expiresIn: string;
  icon: LucideIcon;
}

/** Greeting fallback when Firebase has no display name for the signed-in user. */
export const GREETING_FALLBACK_NAME = "there";

export const AI_SUMMARY = {
  title: "Your health at a glance",
  badgeLabel: "AI summary",
  body:
    "Your recent records look consistent. One lab value in your latest CBC sits slightly " +
    "outside the reference range, so your care team may follow up. Two data-sharing " +
    "requests are waiting for your review.",
  footnote:
    "Illustrative only — the AI summary layer arrives at M5. Confirm decisions with your provider.",
} as const;

/** The four-up figure row. PulseOS tracks consent and records, not vitals. */
export const DASHBOARD_VITALS: readonly {
  id: string;
  label: string;
  value: string;
  unit?: string;
  note: string;
  tone: "success" | "warning" | "info" | "neutral";
}[] = [
  { id: "records", label: "Records", value: "12", note: "Across 2 hospitals", tone: "info" },
  { id: "pending", label: "Pending requests", value: "2", note: "Needs review", tone: "warning" },
  { id: "grants", label: "Active grants", value: "3", note: "1 expiring soon", tone: "success" },
  {
    id: "accesses",
    label: "Accesses",
    value: "8",
    unit: "this month",
    note: "All logged",
    tone: "neutral",
  },
];

export const RECENT_RECORDS: readonly ActivityEntry[] = [
  {
    id: "rec-1",
    title: "Complete Blood Count",
    description: "TMH Jamshedpur · 24 Aug 2026",
    icon: FlaskConical,
    badgeLabel: "CBC",
    tone: "info",
    to: "/records",
  },
  {
    id: "rec-2",
    title: "Chest X-Ray, 2 views",
    description: "CMC Vellore · 11 Aug 2026",
    icon: ScanLine,
    badgeLabel: "XRAY",
    tone: "primary",
    to: "/records",
  },
  {
    id: "rec-3",
    title: "Discharge summary",
    description: "Apollo Hospitals · 2 Aug 2026",
    icon: StickyNote,
    badgeLabel: "Discharge",
    tone: "neutral",
    to: "/records",
  },
  {
    id: "rec-4",
    title: "Metformin 500 mg",
    description: "TMH Jamshedpur · 28 Jul 2026",
    icon: Pill,
    badgeLabel: "Prescription",
    tone: "success",
    to: "/records",
  },
];

export const REVIEW_REQUESTS: readonly ReviewRequest[] = [
  {
    id: "req-1",
    requester: "Dr Thomas George · CMC Vellore",
    purpose: "Cardiology referral follow-up — requesting CBC and Discharge Summary.",
    urgent: true,
  },
  {
    id: "req-2",
    requester: "Dr Priya Nair · Apollo Hospitals",
    purpose: "Radiology review before a scheduled scan — requesting XRAY and MRI.",
    urgent: false,
  },
];

export const EXPIRING_GRANTS: readonly ExpiringGrant[] = [
  {
    id: "grant-1",
    grantee: "Dr Anjali Verma",
    scope: "CBC · TMH Jamshedpur",
    expiresIn: "Expires in 6 days",
    icon: KeyRound,
  },
  {
    id: "grant-2",
    grantee: "Dr Thomas George",
    scope: "Discharge Summary · CMC Vellore",
    expiresIn: "Expires in 21 days",
    icon: KeyRound,
  },
];

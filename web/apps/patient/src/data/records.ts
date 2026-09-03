// Mock medical-record data for the Records page. Static by design: this slice is
// presentation only, so nothing here calls the API. The shapes mirror what
// GET /api/v1/records already returns (docs/DOMAIN_MODEL.md §1 — a DocumentReference-
// shaped row plus its category and uploading hospital), so wiring it later is a swap of
// the source, not a rewrite of the components.

import { FileText, FlaskConical, Pill, ScanLine, StickyNote, type LucideIcon } from "lucide-react";

import type { Tone } from "@/components/dashboard/StatusBadge";

/** The filter vocabulary shown as chips. "All" is the default view. */
export const RECORD_FILTERS = [
  "All",
  "Lab Reports",
  "Prescriptions",
  "Imaging",
  "Visit Notes",
  "Discharge Summary",
] as const;

export type RecordFilter = (typeof RECORD_FILTERS)[number];

/** A record's category — the filter labels minus "All". */
export type RecordCategory = Exclude<RecordFilter, "All">;

export interface MedicalRecord {
  id: string;
  title: string;
  /** Uploading hospital. */
  provider: string;
  doctor: string;
  /** Pre-formatted for display; the API returns an ISO date. */
  date: string;
  category: RecordCategory;
  description: string;
}

/** Icon and badge tone per category, so cards and the panel agree. */
export const CATEGORY_STYLE: Record<RecordCategory, { icon: LucideIcon; tone: Tone }> = {
  "Lab Reports": { icon: FlaskConical, tone: "info" },
  Prescriptions: { icon: Pill, tone: "success" },
  Imaging: { icon: ScanLine, tone: "primary" },
  "Visit Notes": { icon: StickyNote, tone: "neutral" },
  "Discharge Summary": { icon: FileText, tone: "warning" },
};

export const MEDICAL_RECORDS: readonly MedicalRecord[] = [
  {
    id: "rec-1042",
    title: "Complete Blood Count",
    provider: "TMH Jamshedpur",
    doctor: "Dr Anjali Verma",
    date: "24 Aug 2026",
    category: "Lab Reports",
    description:
      "Routine full blood count. Haemoglobin and platelet counts within range; white cell count marginally elevated.",
  },
  {
    id: "rec-1039",
    title: "Chest X-Ray, 2 views",
    provider: "CMC Vellore",
    doctor: "Dr Thomas George",
    date: "11 Aug 2026",
    category: "Imaging",
    description:
      "Two-view chest radiograph requested before a cardiology consult. Lungs clear, heart size normal, no acute findings.",
  },
  {
    id: "rec-1035",
    title: "Discharge summary — day care",
    provider: "Apollo Hospitals",
    doctor: "Dr Priya Nair",
    date: "2 Aug 2026",
    category: "Discharge Summary",
    description:
      "Day-care admission for observation following a fainting episode. Discharged the same evening with follow-up advice.",
  },
  {
    id: "rec-1031",
    title: "Metformin 500 mg",
    provider: "TMH Jamshedpur",
    doctor: "Dr Anjali Verma",
    date: "28 Jul 2026",
    category: "Prescriptions",
    description: "Twice daily with meals for three months. One repeat remaining before review.",
  },
  {
    id: "rec-1024",
    title: "Cardiology consultation note",
    provider: "CMC Vellore",
    doctor: "Dr Thomas George",
    date: "14 Jul 2026",
    category: "Visit Notes",
    description:
      "Initial cardiology review for intermittent palpitations. ECG unremarkable; ambulatory monitoring advised.",
  },
  {
    id: "rec-1018",
    title: "Lipid profile",
    provider: "Apollo Hospitals",
    doctor: "Dr Priya Nair",
    date: "30 Jun 2026",
    category: "Lab Reports",
    description:
      "Fasting lipid panel. Total cholesterol and LDL slightly above target; dietary advice given.",
  },
];

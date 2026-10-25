// Mock settings data for the Settings page. Static by design: this slice is presentation
// only, so nothing here calls the API.
//
// The backend models consent, records and audit (docs/DOMAIN_MODEL.md §1) but not patient
// preferences, so there is no endpoint to mirror yet. The shapes below stay deliberately
// flat — a stable id, a label, a default — so a preferences endpoint later is a change of
// source, not of components.

import {
  Bell,
  Download,
  KeyRound,
  Palette,
  ShieldCheck,
  Trash2,
  type LucideIcon,
} from "lucide-react";

/** One switchable preference. The id keys its state and never changes. */
export interface PreferenceToggle {
  id: string;
  label: string;
  description: string;
  /** Where the switch starts, and what Reset to Defaults returns it to. */
  defaultOn: boolean;
}

/** A card of related preferences. */
export interface PreferenceGroup {
  id: string;
  title: string;
  /** One line under the card title, saying what the group governs. */
  description: string;
  icon: LucideIcon;
  toggles: readonly PreferenceToggle[];
}

export const PREFERENCE_GROUPS: readonly PreferenceGroup[] = [
  {
    id: "notifications",
    title: "Notifications",
    description: "Choose what PulseOS tells you about, and when.",
    icon: Bell,
    toggles: [
      {
        id: "notify-consent-requests",
        label: "New consent requests",
        description: "Alert me as soon as a doctor asks for access to my records.",
        defaultOn: true,
      },
      {
        id: "notify-record-added",
        label: "New records available",
        description: "Tell me when a hospital adds a report to my health record.",
        defaultOn: true,
      },
      {
        id: "notify-record-access",
        label: "Record access activity",
        description: "Notify me each time a provider opens or downloads a record.",
        defaultOn: false,
      },
      {
        id: "notify-grant-expiry",
        label: "Grants about to expire",
        description: "Remind me a week before an active grant lapses.",
        defaultOn: true,
      },
    ],
  },
  {
    id: "sharing",
    title: "Sharing Defaults",
    description: "The rules PulseOS applies to every new access request.",
    icon: ShieldCheck,
    toggles: [
      {
        id: "sharing-require-purpose",
        label: "Require a stated purpose",
        description: "Set aside requests that do not say why the records are needed.",
        defaultOn: true,
      },
      {
        id: "sharing-auto-expire",
        label: "Expire grants automatically",
        description: "End every new grant on its expiry date without asking me again.",
        defaultOn: true,
      },
      {
        id: "sharing-research",
        label: "Anonymised research",
        description: "Allow de-identified copies of my records in approved studies.",
        defaultOn: false,
      },
    ],
  },
  {
    id: "security",
    title: "Security",
    description: "Extra checks on top of Google Sign-In.",
    icon: KeyRound,
    toggles: [
      {
        id: "security-two-factor",
        label: "Two-factor authentication",
        description: "Ask for a verification code as well as my Google account.",
        defaultOn: true,
      },
      {
        id: "security-new-device",
        label: "New device sign-in alerts",
        description: "Email me when my account is opened on a device I have not used before.",
        defaultOn: true,
      },
      {
        id: "security-confirm-downloads",
        label: "Confirm before downloads",
        description: "Ask me to sign in again before a record leaves the portal.",
        defaultOn: false,
      },
    ],
  },
  {
    id: "appearance",
    title: "Appearance",
    description: "How the portal looks on this device.",
    icon: Palette,
    toggles: [
      {
        id: "appearance-dark-mode",
        label: "Dark mode",
        description: "Use the dark palette instead of following the system setting.",
        defaultOn: false,
      },
      {
        id: "appearance-large-text",
        label: "Larger text",
        description: "Increase body text across the portal for easier reading.",
        defaultOn: false,
      },
      {
        id: "appearance-reduce-motion",
        label: "Reduce motion",
        description: "Turn off the transitions used on cards and menus.",
        defaultOn: false,
      },
    ],
  },
];

/** Which switches are on, keyed by PreferenceToggle.id. */
export type PreferenceState = Readonly<Record<string, boolean>>;

/** Every declared preference, in the order its group declares it. */
const ALL_TOGGLES: readonly PreferenceToggle[] = PREFERENCE_GROUPS.flatMap(
  (group) => group.toggles,
);

/** The state the page opens in: every group's declared defaults. */
export function defaultPreferences(): PreferenceState {
  return Object.fromEntries(ALL_TOGGLES.map((toggle) => [toggle.id, toggle.defaultOn]));
}

/** True while nothing has been changed — keeps Reset to Defaults disabled until it would do something. */
export function isDefaultPreferences(state: PreferenceState): boolean {
  return ALL_TOGGLES.every((toggle) => (state[toggle.id] ?? toggle.defaultOn) === toggle.defaultOn);
}

export interface LocaleSetting {
  label: string;
  value: string;
}

/** Fixed for the demo: the portal ships one locale, so these read as facts, not controls. */
export const LOCALE_SETTINGS: readonly LocaleSetting[] = [
  { label: "Language", value: "English (India)" },
  { label: "Time Zone", value: "India Standard Time (GMT+5:30)" },
  { label: "Date Format", value: "DD MMM YYYY" },
  { label: "Units", value: "Metric (kg, cm, °C)" },
];

export const LOCALE_CARD = {
  title: "Language & Region",
  description: "How dates, units and text are shown to you.",
} as const;

export interface DataControl {
  id: string;
  title: string;
  description: string;
  actionLabel: string;
  icon: LucideIcon;
  /** Renders the row and its button in the destructive tone. */
  destructive: boolean;
  /** False for an action with no backend yet: the button renders disabled, never dead. */
  available: boolean;
}

export const DATA_CONTROLS: readonly DataControl[] = [
  {
    id: "export",
    title: "Export health data",
    description:
      "Download your structured clinical records as a FHIR R4 JSON bundle. Uploaded PDFs " +
      "and images are not included in the bundle — download those from Medical Records.",
    actionLabel: "Export FHIR (JSON)",
    icon: Download,
    destructive: false,
    available: true,
  },
  {
    id: "delete",
    title: "Delete account",
    description: "Permanently close this account and revoke every active grant.",
    actionLabel: "Delete Account",
    icon: Trash2,
    destructive: true,
    available: false,
  },
];

export const DATA_CARD = {
  title: "Your Data",
  description: "Take a copy of your records, or close the account entirely.",
} as const;

/** Copy for the standing note at the foot of the page. */
export const SETTINGS_GUIDANCE = {
  title: "About These Settings",
  body:
    "Preferences change how PulseOS behaves for you. They never widen who can read your " +
    "records — that is decided only by the consent you grant.",
  points: [
    "Turning a notification off does not stop the event being written to your Audit History.",
    "Sharing defaults apply to new requests; grants you already approved keep their own terms.",
    "Your Pulse Health ID and your medical records are unaffected by anything on this page.",
  ],
} as const;

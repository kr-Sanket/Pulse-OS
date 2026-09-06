// Settings: notification, sharing, security and appearance preferences, the display locale,
// and the account-level data actions.
//
// Presentation only — every option comes from src/data/settings.ts and nothing here calls
// the API. Switch positions are local UI state so the controls respond and Reset to Defaults
// has something to restore; nothing is persisted, and Export Data / Delete Account are
// visual per spec.

import { RotateCcw } from "lucide-react";
import { useState } from "react";

import { DataControlsCard } from "@/components/settings/DataControlsCard";
import { LocaleCard } from "@/components/settings/LocaleCard";
import { PreferenceGroupCard } from "@/components/settings/PreferenceGroupCard";
import { SettingsInfoCard } from "@/components/settings/SettingsInfoCard";
import { Button } from "@pulseos/ui";

import {
  PREFERENCE_GROUPS,
  defaultPreferences,
  isDefaultPreferences,
  type PreferenceState,
} from "@/data/settings";

export function SettingsPage() {
  const [preferences, setPreferences] = useState<PreferenceState>(defaultPreferences);

  function togglePreference(id: string, checked: boolean) {
    setPreferences((current) => ({ ...current, [id]: checked }));
  }

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="text-foreground text-2xl font-semibold tracking-tight">Settings</h2>
          <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
            Control how PulseOS notifies you, protects your account and shares your health data.
          </p>
        </div>
        <Button
          variant="outline"
          className="gap-2"
          disabled={isDefaultPreferences(preferences)}
          onClick={() => setPreferences(defaultPreferences())}
        >
          <RotateCcw className="size-4" aria-hidden />
          Reset to Defaults
        </Button>
      </div>

      <section aria-labelledby="preferences-heading" className="space-y-4">
        <h3 id="preferences-heading" className="text-sm font-semibold">
          Preferences
        </h3>
        <div className="grid items-start gap-6 lg:grid-cols-2">
          {PREFERENCE_GROUPS.map((group) => (
            <PreferenceGroupCard
              key={group.id}
              group={group}
              values={preferences}
              onToggle={togglePreference}
            />
          ))}
        </div>
      </section>

      <div className="space-y-6">
        <LocaleCard />
        <DataControlsCard />
      </div>

      <SettingsInfoCard />
    </div>
  );
}

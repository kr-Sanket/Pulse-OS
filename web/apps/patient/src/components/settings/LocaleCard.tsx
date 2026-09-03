// Language and region: how dates, units and text are written for this patient. Fixed for
// the demo — the portal ships one locale, so these are stated rather than editable.

import { Globe } from "lucide-react";

import { Detail } from "@/components/common/Detail";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { LOCALE_CARD, LOCALE_SETTINGS } from "@/data/settings";

export function LocaleCard() {
  return (
    <SectionCard title={LOCALE_CARD.title} icon={Globe} contentClassName="space-y-4 pt-1">
      <p className="text-muted-foreground text-sm leading-relaxed">{LOCALE_CARD.description}</p>
      <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-4">
        {LOCALE_SETTINGS.map((setting) => (
          <Detail key={setting.label} label={setting.label}>
            {setting.value}
          </Detail>
        ))}
      </dl>
    </SectionCard>
  );
}

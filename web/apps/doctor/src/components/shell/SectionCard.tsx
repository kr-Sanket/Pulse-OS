// A titled panel: card, optional icon + title, content. Every panel in the portal goes
// through this, so header spacing and icon alignment are defined once.

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@pulseos/ui";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface SectionCardProps {
  title: string;
  icon?: LucideIcon;
  description?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

export function SectionCard({
  title,
  icon: Icon,
  description,
  children,
  className,
  contentClassName,
}: SectionCardProps) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {Icon === undefined ? null : <Icon className="text-primary size-[18px]" aria-hidden />}
          {title}
        </CardTitle>
        {description === undefined ? null : (
          <p className="text-muted-foreground text-sm leading-relaxed">{description}</p>
        )}
      </CardHeader>
      <CardContent className={cn("pt-1", contentClassName)}>{children}</CardContent>
    </Card>
  );
}

// A dashboard section: card, optional icon + title, optional header action, content.
// Every panel on the dashboard goes through this, so header spacing and the icon/title
// alignment are defined once.

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button, Card, CardContent, CardHeader, CardTitle, cn } from "@pulseos/ui";

export interface SectionCardAction {
  label: string;
  to: string;
  icon?: LucideIcon;
}

export interface SectionCardProps {
  title: string;
  icon?: LucideIcon;
  /** Optional link rendered at the trailing edge of the header. */
  action?: SectionCardAction;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

export function SectionCard({
  title,
  icon: Icon,
  action,
  children,
  className,
  contentClassName,
}: SectionCardProps) {
  const ActionIcon = action?.icon;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          {Icon === undefined ? null : <Icon className="text-primary size-[18px]" aria-hidden />}
          {title}
        </CardTitle>
        {action === undefined ? null : (
          <Button asChild variant="ghost" size="sm">
            <Link to={action.to}>
              {action.label}
              {ActionIcon === undefined ? null : <ActionIcon className="size-4" aria-hidden />}
            </Link>
          </Button>
        )}
      </CardHeader>
      <CardContent className={cn("pt-1", contentClassName)}>{children}</CardContent>
    </Card>
  );
}

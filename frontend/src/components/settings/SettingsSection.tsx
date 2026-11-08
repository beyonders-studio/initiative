import type { ReactNode } from "react";

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";

export interface SettingsSectionProps {
  /** What this section is for, in the words the reader would use. Left out
   *  when the tab it sits on already says it. */
  title?: ReactNode;
  /** One line under the title. Say what the controls do, not that they exist. */
  description?: ReactNode;
  /** A control that belongs to the section as a whole — a link, an add button. */
  action?: ReactNode;
  /** Pinned to the bottom of the card, where a Save button goes. */
  footer?: ReactNode;
  /** Draws the section as a consequence rather than a preference. */
  destructive?: boolean;
  /** Applied to the card, for the rare section that needs to bleed to its edge. */
  className?: string;
  /** Applied to the body, whose default is a comfortable vertical rhythm. */
  contentClassName?: string;
  /** Left out for a section whose header says everything, such as a status. */
  children?: ReactNode;
}

/**
 * One block of settings: a heading, a line of explanation, and the controls.
 *
 * Every settings tab is a stack of these. Having one component decide the
 * heading weight, the gap under the description and where a Save button sits
 * is what keeps nine tabs written by different hands looking like one screen —
 * and it means a new tab starts from the right answer instead of copying
 * whichever neighbour it was pasted from.
 */
export const SettingsSection = ({
  title,
  description,
  action,
  footer,
  destructive,
  className,
  contentClassName,
  children,
}: SettingsSectionProps) => {
  const hasHeader = Boolean(title || description || action);
  return (
    <Card className={cn(destructive && "border-destructive/50", className)}>
      {hasHeader ? (
        <CardHeader
          className={cn(action && "flex-row items-start justify-between gap-4 space-y-0")}
        >
          <div className="min-w-0 space-y-1.5">
            {title ? (
              <CardTitle className={cn(destructive && "text-destructive")}>{title}</CardTitle>
            ) : null}
            {description ? <CardDescription>{description}</CardDescription> : null}
          </div>
          {action ? <div className="shrink-0">{action}</div> : null}
        </CardHeader>
      ) : null}
      {children ? (
        <CardContent className={cn("space-y-4", !hasHeader && "pt-6", contentClassName)}>
          {children}
        </CardContent>
      ) : null}
      {footer ? <CardFooter className="gap-3 border-t pt-6">{footer}</CardFooter> : null}
    </Card>
  );
};

export interface SettingsRowProps {
  label: ReactNode;
  description?: ReactNode;
  /** Ties the label to the control it names. */
  htmlFor?: string;
  /** The control, at the end of the row. */
  children?: ReactNode;
  /** Shown under the row, for what the control opens up when it is on. */
  below?: ReactNode;
}

/**
 * One setting inside a section: its name, what it does, and its control.
 *
 * Rows stack with a rule between them, so a section of several settings reads
 * as a list. On a phone the control drops under the text.
 */
export const SettingsRow = ({ label, description, htmlFor, children, below }: SettingsRowProps) => (
  <div className="space-y-3 border-b pb-4 last:border-b-0 last:pb-0">
    <div className="flex flex-wrap items-center justify-between gap-2 gap-x-6">
      <div className="min-w-0 space-y-0.5">
        {htmlFor ? (
          <Label htmlFor={htmlFor}>{label}</Label>
        ) : (
          <p className="font-medium text-sm">{label}</p>
        )}
        {description ? <p className="text-muted-foreground text-sm">{description}</p> : null}
      </div>
      {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
    </div>
    {below}
  </div>
);

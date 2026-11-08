import { type ReactNode, useId } from "react";

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/ui/card";
import { FieldContext } from "@/ui/field";
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
  /** Draws a heading over a rule instead of a card, for a section inside a
   *  sheet, which is a surface of its own. */
  plain?: boolean;
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
  plain,
  className,
  contentClassName,
  children,
}: SettingsSectionProps) => {
  const hasHeader = Boolean(title || description || action);
  const Title = plain ? "h3" : CardTitle;
  return (
    <Card
      className={cn(
        plain && "space-y-3 rounded-none border-0 bg-transparent shadow-none",
        destructive && "border-destructive/50",
        className
      )}
    >
      {hasHeader ? (
        <CardHeader
          className={cn(
            plain && "border-b p-0 pb-2",
            action && "flex-row flex-wrap items-start gap-4 space-y-0"
          )}
        >
          {title || description ? (
            <div className={cn("min-w-0 space-y-1.5", action && "grow basis-64")}>
              {title ? (
                <Title
                  className={cn(
                    plain && "font-semibold text-sm",
                    destructive && "text-destructive"
                  )}
                >
                  {title}
                </Title>
              ) : null}
              {description ? <CardDescription>{description}</CardDescription> : null}
            </div>
          ) : null}
          {action ? <div className="ms-auto shrink-0">{action}</div> : null}
        </CardHeader>
      ) : null}
      {children ? (
        <CardContent
          className={cn("space-y-4", plain ? "p-0" : !hasHeader && "pt-6", contentClassName)}
        >
          {children}
        </CardContent>
      ) : null}
      {footer ? (
        <CardFooter className={cn("gap-3 border-t pt-6", plain && "p-0 pt-3")}>{footer}</CardFooter>
      ) : null}
    </Card>
  );
};

export interface SettingsRowProps {
  label: ReactNode;
  description?: ReactNode;
  /** The control's id, for something else that names it; one is made otherwise. */
  htmlFor?: string;
  /** The control, at the end of the row. The kit's controls take the row's id
   *  and description, so the label names the control and a click on the label
   *  reaches it. */
  children?: ReactNode;
  /** Shown under the row, for what the control opens up when it is on. */
  below?: ReactNode;
}

/**
 * One setting inside a section: its name, what it does, and its control.
 *
 * Rows stack with a rule between them, so a section of several settings reads
 * as a list. Where the text and the control do not fit side by side, as on a
 * phone, the control drops under the text.
 */
export const SettingsRow = ({ label, description, htmlFor, children, below }: SettingsRowProps) => {
  const madeId = useId();
  const id = htmlFor ?? madeId;
  const descriptionId = description ? `${id}-description` : undefined;
  return (
    <div className="space-y-3 border-b pb-4 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2 gap-x-6">
        <div className="min-w-0 grow basis-64 space-y-0.5">
          {children ? (
            <Label htmlFor={id} className="leading-snug">
              {label}
            </Label>
          ) : (
            <p className="font-medium text-sm">{label}</p>
          )}
          {description ? (
            <p id={descriptionId} className="text-muted-foreground text-sm">
              {description}
            </p>
          ) : null}
        </div>
        {children ? (
          <div className="flex shrink-0 items-center gap-2">
            <FieldContext value={{ id, "aria-describedby": descriptionId }}>
              {children}
            </FieldContext>
          </div>
        ) : null}
      </div>
      {below}
    </div>
  );
};

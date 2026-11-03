import { CircleHelp } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { PART_MARK } from "@/components/tasks/SmartTitleParts";
import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useSmartTitlesOn } from "@/hooks/useSmartTitle";
import type { TitlePartType } from "@/lib/smartTitle";
import { cn } from "@/lib/utils";

/** What a title can say, each with the mark its words get in the title. */
export const HINTS: { key: string; type: TitlePartType; note?: boolean }[] = [
  { key: "dates", type: "due" },
  { key: "times", type: "due" },
  { key: "repeats", type: "repeat", note: true },
  { key: "priority", type: "priority", note: true },
  { key: "tags", type: "tag" },
  { key: "people", type: "person" },
  { key: "type", type: "type", note: true },
];

/**
 * What a new task's title is read for, with examples, behind a small help
 * button beside it. Pointing at it or focusing it shows the card; on a touch
 * screen a tap opens it and another closes it. Drawn only where the reader
 * has titles read.
 */
export const SmartTitleHints = ({ className }: { className?: string }) => {
  const { t } = useTranslation("tasks");
  const on = useSmartTitlesOn();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  // Where a press started, and whether the card was open then: a tap toggles
  // it, where a click with a mouse or a key only ever opens it.
  const press = useRef<{ touch: boolean; wasOpen: boolean }>({ touch: false, wasOpen: false });
  if (!on) return null;

  return (
    <HoverCard open={open} onOpenChange={setOpen} openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <Button
          ref={trigger}
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("smartTitle.hints.button")}
          aria-expanded={open}
          className={cn("text-muted-foreground", className)}
          onPointerDown={(event) => {
            press.current = { touch: event.pointerType === "touch", wasOpen: open };
          }}
          onClick={() => {
            setOpen(press.current.touch ? !press.current.wasOpen : true);
            press.current = { touch: false, wasOpen: false };
          }}
        >
          <CircleHelp aria-hidden="true" />
        </Button>
      </HoverCardTrigger>
      <HoverCardContent
        align="end"
        className="w-72 space-y-3"
        // The button decides for itself whether a tap on it closes the card.
        onPointerDownOutside={(event) => {
          if (trigger.current?.contains(event.target as Node)) event.preventDefault();
        }}
      >
        <p className="font-medium text-sm">{t("smartTitle.hints.title")}</p>
        <dl className="space-y-2">
          {HINTS.map(({ key, type, note }) => (
            <div key={key} className="space-y-1">
              <dt className="font-medium text-muted-foreground text-xs">
                {t(`smartTitle.hints.${key}.label` as never)}
              </dt>
              <dd className="flex flex-wrap gap-1">
                {(t(`smartTitle.hints.${key}.examples` as never) as string)
                  .split("|")
                  .map((example) => (
                    <code
                      key={example}
                      className={cn("rounded-sm px-1 font-mono text-xs", PART_MARK[type])}
                    >
                      {example}
                    </code>
                  ))}
              </dd>
              {note ? (
                <dd className="text-muted-foreground text-xs">
                  {t(`smartTitle.hints.${key}.note` as never)}
                </dd>
              ) : null}
            </div>
          ))}
        </dl>
        <p className="text-muted-foreground text-xs">{t("smartTitle.hints.footer")}</p>
      </HoverCardContent>
    </HoverCard>
  );
};

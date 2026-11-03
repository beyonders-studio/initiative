import { format } from "date-fns";
import { AtSign, CalendarClock, Hash, Repeat, X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { priorityDotClass } from "@/components/projects/projectTasksConfig";
import { TaskTypeIcon } from "@/components/tasks/TaskTypeOption";
import { useDateLocale } from "@/hooks/useDateLocale";
import { summarizeRecurrence } from "@/lib/recurrence";
import type { TitlePart, TitlePartType, TitleReading } from "@/lib/smartTitle";
import { dateTimePattern } from "@/lib/timeFormat";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";
import type { TranslateFn } from "@/types/i18n";

/** The marks drawn behind what a title's parts say, by their type. */
export const PART_MARK: Record<TitlePartType, string> = {
  type: "bg-indigo-500/20",
  due: "bg-sky-500/20",
  repeat: "bg-violet-500/20",
  priority: "bg-amber-500/25",
  tag: "bg-emerald-500/20",
  person: "bg-pink-500/20",
};

const Chip = ({
  type,
  label,
  keepLabel,
  onKeep,
  icon,
}: {
  type: TitlePartType;
  label: string;
  keepLabel: string;
  onKeep: () => void;
  icon: ReactNode;
}) => (
  <li
    className={cn(
      "inline-flex max-w-full items-center gap-1 rounded-full py-0.5 ps-2 pe-0.5 text-foreground text-xs",
      PART_MARK[type]
    )}
  >
    {icon}
    <span className="truncate">{label}</span>
    <button
      type="button"
      onClick={onKeep}
      aria-label={keepLabel}
      title={keepLabel}
      className="inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-background/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <X className="size-3" aria-hidden="true" />
    </button>
  </li>
);

/**
 * What a new task's title was read as, one chip for each thing it sets. Taking
 * a chip off keeps its words in the title as they were typed.
 */
export const SmartTitleParts = ({
  reading,
  onKeep,
  className,
}: {
  reading: TitleReading | null;
  onKeep: (keys: string[]) => void;
  className?: string;
}) => {
  const { t } = useTranslation(["tasks", "dates"]);
  const locale = useDateLocale();
  if (!reading || reading.parts.length === 0) return null;
  const { parts } = reading;

  const of = (type: TitlePartType, id?: number) =>
    parts.filter((part) => part.type === type && (id === undefined || part.id === id));
  const keys = (picked: TitlePart[]) => picked.map((part) => part.key);
  const keep = (picked: TitlePart[]) => ({
    keepLabel: t("smartTitle.keep", { text: picked.map((part) => part.text).join(" … ") }),
    onKeep: () => onKeep(keys(picked)),
  });
  const icon = "size-3 shrink-0 text-muted-foreground";

  const chips: ReactNode[] = [];
  const type = of("type");
  if (reading.type && type.length) {
    chips.push(
      <Chip
        key="type"
        type="type"
        label={reading.type.name}
        icon={<TaskTypeIcon type={reading.type} className="size-3" />}
        {...keep(type)}
      />
    );
  }
  const due = of("due");
  if (reading.due && due.length) {
    const when = format(
      reading.due,
      reading.dueHasTime ? dateTimePattern("EEE, MMM d") : "EEE, MMM d",
      { locale }
    );
    chips.push(
      <Chip
        key="due"
        type="due"
        label={t("smartTitle.due", { when })}
        icon={<CalendarClock className={icon} aria-hidden="true" />}
        {...keep(due)}
      />
    );
  }
  const repeat = of("repeat");
  if (reading.repeat && repeat.length) {
    chips.push(
      <Chip
        key="repeat"
        type="repeat"
        label={summarizeRecurrence(
          reading.repeat,
          { referenceDate: reading.due?.toISOString() ?? null, strategy: reading.repeatStrategy },
          t as TranslateFn
        )}
        icon={<Repeat className={icon} aria-hidden="true" />}
        {...keep(repeat)}
      />
    );
  }
  const priority = of("priority");
  if (reading.priority && priority.length) {
    chips.push(
      <Chip
        key="priority"
        type="priority"
        label={t("smartTitle.priority", {
          priority: t(`priority.${reading.priority}` as never),
        })}
        icon={
          <span
            aria-hidden="true"
            className={cn("size-2 shrink-0 rounded-full", priorityDotClass[reading.priority])}
          />
        }
        {...keep(priority)}
      />
    );
  }
  for (const tag of reading.tags) {
    chips.push(
      <Chip
        key={`tag-${tag.id}`}
        type="tag"
        label={tag.name}
        icon={<Hash className={icon} aria-hidden="true" />}
        {...keep(of("tag", tag.id))}
      />
    );
  }
  for (const person of reading.people) {
    chips.push(
      <Chip
        key={`person-${person.id}`}
        type="person"
        label={getUserDisplayName(person)}
        icon={<AtSign className={icon} aria-hidden="true" />}
        {...keep(of("person", person.id))}
      />
    );
  }

  return (
    <ul aria-label={t("smartTitle.read")} className={cn("flex flex-wrap gap-1.5", className)}>
      {chips}
    </ul>
  );
};

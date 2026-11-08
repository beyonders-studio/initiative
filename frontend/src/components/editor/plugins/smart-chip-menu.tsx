import {
  CalendarClock,
  CircleDot,
  Flag,
  Gauge,
  ListChecks,
  Mail,
  Phone,
  SquareCheck,
  User,
} from "lucide-react";
import type { JSX } from "react";

import { SmartChipKind } from "@/api/generated/initiativeAPI.schemas";

/**
 * How each chip is offered: what it is called, what it looks like, and what
 * typing finds it.
 *
 * Keyed by the generated pair, so a chip the server adds cannot be silently
 * missing here — `smart-chip-picker-plugin.test.ts` fails if one is.
 *
 * Its own module because both ways in read it: the `/` menu builds an entry per
 * fact from it, and the toolbar's dialog uses it to name the facts a chosen
 * thing has.
 */
export const SMART_CHIP_MENU: Record<
  SmartChipKind,
  { labelKey: string; icon: JSX.Element; keywords: string[] }
> = {
  [SmartChipKind["task:status"]]: {
    labelKey: "smartChips.taskStatus",
    icon: <CircleDot className="size-4" />,
    keywords: ["status", "task", "state", "column", "chip", "done"],
  },
  [SmartChipKind["task:assignee"]]: {
    labelKey: "smartChips.taskAssignee",
    icon: <User className="size-4" />,
    keywords: ["assignee", "task", "who", "owner", "chip"],
  },
  [SmartChipKind["task:due"]]: {
    labelKey: "smartChips.taskDue",
    icon: <CalendarClock className="size-4" />,
    keywords: ["due", "task", "date", "deadline", "chip"],
  },
  [SmartChipKind["task:priority"]]: {
    labelKey: "smartChips.taskPriority",
    icon: <Flag className="size-4" />,
    keywords: ["priority", "task", "urgent", "chip"],
  },
  [SmartChipKind["task:checklist"]]: {
    labelKey: "smartChips.taskChecklist",
    icon: <SquareCheck className="size-4" />,
    keywords: ["checklist", "checkbox", "tick", "todo", "done", "attendance", "task", "chip"],
  },
  [SmartChipKind["counter:value"]]: {
    labelKey: "smartChips.counterValue",
    icon: <Gauge className="size-4" />,
    keywords: ["counter", "count", "number", "value", "chip"],
  },
  [SmartChipKind["project:progress"]]: {
    labelKey: "smartChips.projectProgress",
    icon: <ListChecks className="size-4" />,
    keywords: ["project", "progress", "tasks", "done", "how far", "chip"],
  },
  [SmartChipKind["calendar_event:when"]]: {
    labelKey: "smartChips.eventWhen",
    icon: <CalendarClock className="size-4" />,
    keywords: ["event", "when", "date", "calendar", "chip"],
  },
  [SmartChipKind["contact:phone"]]: {
    labelKey: "smartChips.contactPhone",
    icon: <Phone className="size-4" />,
    keywords: ["contact", "phone", "number", "call", "chip"],
  },
  [SmartChipKind["contact:email"]]: {
    labelKey: "smartChips.contactEmail",
    icon: <Mail className="size-4" />,
    keywords: ["contact", "email", "mail", "address", "chip"],
  },
};

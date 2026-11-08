/**
 * Every home widget's component, by type. `lib/home/widgetTypes` lists the
 * types and their sizes; this says how each one is drawn, and the record's
 * type makes a missing one a compile error.
 */

import {
  Activity,
  Bookmark,
  CalendarClock,
  CalendarDays,
  Clock,
  Crosshair,
  Hand,
  History,
  Rocket,
  SquareCheckBig,
  Trophy,
  Users,
} from "lucide-react";

import type { HomeWidgetType } from "@/lib/home/widgetTypes";

import { ActivitySettings, ActivityWidget } from "./ActivityWidget";
import { BookmarksSettings, BookmarksWidget } from "./BookmarksWidget";
import { CalendarWidget } from "./CalendarWidget";
import { ClockSettings, ClockWidget } from "./ClockWidget";
import { ComingUpSettings, ComingUpWidget } from "./ComingUpWidget";
import { CommunitiesWidget } from "./CommunitiesWidget";
import { FocusWidget } from "./FocusWidget";
import { GettingStartedWidget } from "./GettingStartedWidget";
import { GreetingSettings, GreetingWidget } from "./GreetingWidget";
import { ProgressWidget } from "./ProgressWidget";
import { RecentSettings, RecentWidget } from "./RecentWidget";
import { TasksSettings, TasksWidget } from "./TasksWidget";
import type { HomeWidgetDefinition } from "./types";

export const HOME_WIDGETS: Record<HomeWidgetType, HomeWidgetDefinition> = {
  greeting: { icon: Hand, Component: GreetingWidget, Settings: GreetingSettings },
  gettingStarted: { icon: Rocket, Component: GettingStartedWidget },
  focus: { icon: Crosshair, Component: FocusWidget },
  tasks: { icon: SquareCheckBig, Component: TasksWidget, Settings: TasksSettings },
  comingUp: { icon: CalendarClock, Component: ComingUpWidget, Settings: ComingUpSettings },
  calendar: { icon: CalendarDays, Component: CalendarWidget },
  activity: { icon: Activity, Component: ActivityWidget, Settings: ActivitySettings },
  recent: { icon: History, Component: RecentWidget, Settings: RecentSettings },
  bookmarks: { icon: Bookmark, Component: BookmarksWidget, Settings: BookmarksSettings },
  communities: { icon: Users, Component: CommunitiesWidget },
  progress: { icon: Trophy, Component: ProgressWidget },
  clock: { icon: Clock, Component: ClockWidget, Settings: ClockSettings },
};

export type { HomeWidgetDefinition } from "./types";

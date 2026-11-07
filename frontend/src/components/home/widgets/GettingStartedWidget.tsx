/**
 * Getting started: a few first things to do, hosted by Yonder, each ticking
 * itself off when it has actually happened rather than when somebody clicks
 * it — a community joined, a task made, somebody invited, a face added.
 *
 * What it asks depends on why they signed up (the `path` the first home page
 * was made with): somebody who joined a community is not asked to invite
 * people to it, and somebody with a space of their own is not asked to find
 * one. Once everything is done it says so, and offers to go.
 *
 * Only getting the app cannot be seen from here, so opening the download page
 * is what ticks it.
 */

import { Capacitor } from "@capacitor/core";
import { Link } from "@tanstack/react-router";
import { CheckCircle2, Circle, Rocket, X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { HomeWidgetCard } from "@/components/home/HomeWidgetCard";
import { useHomeActions } from "@/components/home/homeActions";
import { YonderSays } from "@/components/start/YonderSays";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useHomeViews } from "@/hooks/useHomeViews";
import { useCreatedTaskCount } from "@/hooks/useOpenTaskCount";
import { useTaskListName } from "@/hooks/useTaskListName";
import { communityPath } from "@/lib/communityUrl";
import type { HomeTaskList } from "@/lib/home/firstHome";
import type { StartPath } from "@/lib/startFlow";
import { toolDetailRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";
import { Progress } from "@/ui/progress";

import type { HomeWidgetProps } from "./types";

const PATHS: StartPath[] = ["personal", "shared", "join", "invite"];

const pathOf = (options: Record<string, unknown>): StartPath =>
  PATHS.includes(options.path as StartPath) ? (options.path as StartPath) : "join";

const listOf = (options: Record<string, unknown>): HomeTaskList | null => {
  const list = options.list as Partial<HomeTaskList> | undefined;
  return list &&
    typeof list.communityId === "number" &&
    typeof list.initiativeId === "number" &&
    typeof list.projectId === "number"
    ? { communityId: list.communityId, initiativeId: list.initiativeId, projectId: list.projectId }
    : null;
};

/** Steps the reader said they have done, for the one this page cannot see. */
const ticked = (options: Record<string, unknown>): string[] =>
  Array.isArray(options.done) ? options.done.filter((id) => typeof id === "string") : [];

interface Step {
  id: string;
  done: boolean;
  title: string;
  hint: string;
  action?: ReactNode;
}

export const GettingStartedWidget = ({ options, onOptionsChange, onRemove }: HomeWidgetProps) => {
  const { t } = useTranslation("home");
  const { user } = useAuth();
  const { communities } = useCommunities();
  const { views, layout } = useHomeViews();
  const { customize } = useHomeActions();
  const createdTasks = useCreatedTaskCount();
  const path = pathOf(options);
  const list = listOf(options);
  const listName = useTaskListName(list).data;
  const done = ticked(options);

  const tick = (id: string) => {
    if (!done.includes(id)) onOptionsChange({ ...options, done: [...done, id] });
  };

  const administered = communities.filter(
    (community) =>
      community.accessType !== "grant" &&
      (community.role === "admin" || community.role === "superadmin")
  );
  // Inviting is offered to somebody running a community of their own; a
  // personal space is nobody else's until its owner decides otherwise.
  const runsOne = path !== "personal" && administered.length > 0;
  const firstCommunity = administered[0] ?? communities[0];

  const linkButton = (to: string, label: string, onClick?: () => void) => (
    <Button asChild size="sm" variant="outline">
      <Link to={to} onClick={onClick}>
        {label}
      </Link>
    </Button>
  );

  const steps: Step[] = [
    {
      id: "community",
      done: communities.length > 0,
      title: t(`widgets.gettingStarted.community.${path}`),
      hint: t("widgets.gettingStarted.community.hint"),
      action: linkButton("/communities", t("widgets.gettingStarted.community.action")),
    },
    {
      id: "task",
      done: (createdTasks.data ?? 0) > 0,
      title: t("widgets.gettingStarted.task.title"),
      hint: listName
        ? t("widgets.gettingStarted.task.hintList", { list: listName })
        : t("widgets.gettingStarted.task.hint"),
      action:
        list && listName
          ? linkButton(
              communityPath(
                list.communityId,
                toolDetailRoute(Tool.project, list.initiativeId, list.projectId)
              ),
              t("widgets.gettingStarted.task.action", { list: listName })
            )
          : linkButton("/my-tools", t("widgets.gettingStarted.task.actionTools")),
    },
    ...(runsOne
      ? [
          {
            id: "invite",
            done: administered.some((community) => community.member_count > 1),
            title: t("widgets.gettingStarted.invite.title"),
            hint: t("widgets.gettingStarted.invite.hint"),
            action: firstCommunity
              ? linkButton(
                  communityPath(firstCommunity.id, "/settings/users"),
                  t("widgets.gettingStarted.invite.action")
                )
              : undefined,
          },
        ]
      : []),
    {
      id: "profile",
      done: Boolean(user?.avatar_url),
      title: t("widgets.gettingStarted.profile.title"),
      hint: t("widgets.gettingStarted.profile.hint"),
      action: linkButton("/profile", t("widgets.gettingStarted.profile.action")),
    },
    {
      id: "app",
      done: Capacitor.isNativePlatform() || done.includes("app"),
      title: t("widgets.gettingStarted.app.title"),
      hint: t("widgets.gettingStarted.app.hint"),
      action: linkButton("/download", t("widgets.gettingStarted.app.action"), () => tick("app")),
    },
    {
      id: "home",
      // Anything arranged, added or taken away, or a second view, counts.
      done: layout.preset === undefined || views.views.length > 1,
      title: t("widgets.gettingStarted.home.title"),
      hint: t("widgets.gettingStarted.home.hint"),
      action: (
        <Button type="button" size="sm" variant="outline" onClick={customize}>
          {t("widgets.gettingStarted.home.action")}
        </Button>
      ),
    },
  ];

  const finished = steps.filter((step) => step.done).length;
  const allDone = finished === steps.length;

  return (
    <HomeWidgetCard
      icon={Rocket}
      title={t("widgets.gettingStarted.title")}
      actions={
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label={t("widgets.gettingStarted.hide")}
          title={t("widgets.gettingStarted.hide")}
          onClick={onRemove}
        >
          <X className="size-4" />
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <YonderSays
            pose={allDone ? "proud" : finished === 0 ? "talking" : "excited"}
            line={
              allDone
                ? t("widgets.gettingStarted.allDone")
                : t(`widgets.gettingStarted.intro.${path}`)
            }
          />
          {allDone ? (
            <Button type="button" size="sm" onClick={onRemove}>
              {t("widgets.gettingStarted.remove")}
            </Button>
          ) : null}
        </div>
        <div className="space-y-1">
          <p className="text-muted-foreground text-xs">
            {t("widgets.gettingStarted.progress", { done: finished, total: steps.length })}
          </p>
          <Progress value={(finished / steps.length) * 100} className="h-1" />
        </div>
        <ol className="grid grid-cols-fill-72/2 gap-2">
          {steps.map((step) => (
            <li
              key={step.id}
              className={cn(
                "flex items-start gap-3 rounded-lg border p-3",
                step.done && "border-transparent bg-muted/50"
              )}
            >
              {step.done ? (
                <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" aria-hidden="true" />
              ) : (
                <Circle
                  className="mt-0.5 size-5 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
              )}
              <div className="min-w-0 flex-1 space-y-2">
                <div>
                  <p className={cn("font-medium text-sm", step.done && "text-muted-foreground")}>
                    {step.title}
                    <span className="sr-only">
                      {step.done ? ` (${t("widgets.gettingStarted.stepDone")})` : ""}
                    </span>
                  </p>
                  {step.done ? null : <p className="text-muted-foreground text-xs">{step.hint}</p>}
                </div>
                {step.done ? null : step.action}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </HomeWidgetCard>
  );
};

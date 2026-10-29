/**
 * One line to add a task to a list, from the home page: the shortest way to a
 * first task, and to the next one. The task is the reader's own, so it lands
 * in their tasks straight away. Where the reader has titles read, what the
 * line says of a type, date, repeat, priority, tags or people is set on it too.
 */

import { Plus } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { usePersonMention } from "@/components/comments/usePersonMention";
import { SmartTitleHints } from "@/components/tasks/SmartTitleHints";
import { SmartTitleParts } from "@/components/tasks/SmartTitleParts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/useAuth";
import { useSmartTitle, useSmartTitlesOn } from "@/hooks/useSmartTitle";
import { useCreateTaskInCommunity } from "@/hooks/useTasks";
import type { HomeTaskList } from "@/lib/home/firstHome";
import { toast } from "@/lib/mascotToast";
import { readingCreate } from "@/lib/smartTaskTitle";

export const QuickAddTask = ({ list, name }: { list: HomeTaskList; name: string }) => {
  const { t } = useTranslation("home");
  const { user } = useAuth();
  const [title, setTitle] = useState("");
  const create = useCreateTaskInCommunity();
  const clean = title.trim();
  const reads = useSmartTitlesOn();
  const smart = useSmartTitle({
    text: title,
    communityId: list.communityId,
    projectId: list.projectId,
    enabled: reads,
  });
  const box = useRef<HTMLInputElement>(null);
  const people = usePersonMention({
    field: box,
    text: title,
    onChange: setTitle,
    members: {
      type: "canOpen",
      tool: Tool.project,
      id: list.projectId,
      communityIdOverride: list.communityId,
    },
    enabled: reads,
    onPick: smart.picked,
  });

  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!clean || create.isPending) return;
        const mine = user ? [user.id] : [];
        create.mutate(
          {
            communityId: list.communityId,
            data: {
              title: clean,
              project_id: list.projectId,
              ...(mine.length ? { assignee_ids: mine } : {}),
              ...(smart.reading ? readingCreate(smart.reading, mine) : {}),
            },
          },
          {
            onSuccess: () => {
              setTitle("");
              smart.reset();
              toast.success(t("widgets.tasks.added", { list: name }));
            },
          }
        );
      }}
    >
      <div className="flex gap-2">
        <div className="relative min-w-0 flex-1">
          <Input
            ref={box}
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
              people.sync(event.target);
            }}
            {...people.handlers}
            placeholder={t("widgets.tasks.addPlaceholder", { list: name })}
            aria-label={t("widgets.tasks.addPlaceholder", { list: name })}
            disabled={create.isPending}
            className={reads ? "pe-9" : undefined}
          />
          {/* Inside the line's end, where it does not take from the box's width. */}
          <SmartTitleHints className="absolute end-0.5 top-1/2 size-8 -translate-y-1/2" />
          {people.popover}
        </div>
        <Button type="submit" disabled={!clean || create.isPending}>
          <Plus className="size-4" aria-hidden="true" />
          {t("widgets.tasks.add")}
        </Button>
      </div>
      <SmartTitleParts reading={smart.reading} onKeep={smart.keep} />
    </form>
  );
};

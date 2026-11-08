/**
 * The published ideas on Initiative Cloud, readable signed in or not: search,
 * the board's statuses to narrow by, most voted or newest first, and the
 * ones the reader voted for. Anywhere else there is no board, and the
 * address leads home.
 */

import { Link, Navigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { IdeaSort } from "@/api/generated/initiativeAPI.schemas";
import { SignInFrame } from "@/components/auth/SignInFrame";
import { IdeaStatusBadge, VoteButton } from "@/components/ideas/IdeaParts";
import { useAuth } from "@/hooks/useAuth";
import { useIdeas } from "@/hooks/useIdeas";
import { Card } from "@/ui/card";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { LoadMore } from "@/ui/load-more";
import { Toggle } from "@/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

const ALL = "all";

export const IdeasPage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const [typed, setTyped] = useState("");
  const search = useDebouncedValue(typed.trim(), 300);
  const [sort, setSort] = useState<IdeaSort>(IdeaSort.votes);
  const [statusId, setStatusId] = useState<number | null>(null);
  const [mine, setMine] = useState(false);
  const query = useIdeas({
    search: search || undefined,
    sort,
    status_id: statusId ?? undefined,
    voted: mine && Boolean(user),
  });

  if (query.isError) return <Navigate to="/" replace />;
  const pages = query.data?.pages ?? [];
  const ideas = pages.flatMap((page) => page.items);
  const statuses = pages[0]?.statuses ?? [];

  return (
    <SignInFrame fillPhone>
      <Card className="w-full max-w-2xl space-y-4 p-4 max-sm:min-h-app max-sm:rounded-none max-sm:border-0 sm:p-6">
        <div className="space-y-1">
          <h1 className="font-semibold text-xl">{t("ideas.title")}</h1>
          <p className="text-muted-foreground text-sm">{t("ideas.lede")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="search"
            className="min-w-0 flex-1 basis-48"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder={t("ideas.search")}
            aria-label={t("ideas.search")}
          />
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            aria-label={t("ideas.sortLabel")}
            value={sort}
            onValueChange={(next) => next && setSort(next as IdeaSort)}
          >
            <ToggleGroupItem value={IdeaSort.votes}>{t("ideas.sort.votes")}</ToggleGroupItem>
            <ToggleGroupItem value={IdeaSort.newest}>{t("ideas.sort.newest")}</ToggleGroupItem>
          </ToggleGroup>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <ToggleGroup
            type="single"
            variant="outline"
            size="sm"
            aria-label={t("ideas.statusLabel")}
            className="flex-wrap justify-start"
            value={statusId === null ? ALL : String(statusId)}
            onValueChange={(next) => next && setStatusId(next === ALL ? null : Number(next))}
          >
            <ToggleGroupItem value={ALL}>{t("ideas.allStatuses")}</ToggleGroupItem>
            {statuses.map((status) => (
              <ToggleGroupItem key={status.id} value={String(status.id)}>
                {status.name}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          {user ? (
            <Toggle variant="outline" size="sm" pressed={mine} onPressedChange={setMine}>
              {t("ideas.votedByMe")}
            </Toggle>
          ) : null}
        </div>
        {query.isSuccess && ideas.length === 0 ? (
          <p className="py-6 text-center text-muted-foreground text-sm">{t("ideas.none")}</p>
        ) : (
          <ul className="divide-y rounded-lg border" aria-label={t("ideas.title")}>
            {ideas.map((idea) => (
              <li key={idea.task_id} className="flex items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1 space-y-0.5">
                  <Link
                    to="/ideas/$taskId"
                    params={{ taskId: String(idea.task_id) }}
                    className="block font-medium hover:underline"
                  >
                    {idea.title}
                  </Link>
                  <div className="flex flex-wrap items-center gap-3 text-muted-foreground text-xs">
                    <IdeaStatusBadge status={idea.status} />
                    <span>{t("ideas.votes", { count: idea.votes })}</span>
                  </div>
                </div>
                <VoteButton idea={idea} next="/ideas" />
              </li>
            ))}
          </ul>
        )}
        <LoadMore
          hasMore={Boolean(query.hasNextPage)}
          loading={query.isFetchingNextPage}
          onLoadMore={() => void query.fetchNextPage()}
        />
      </Card>
    </SignInFrame>
  );
};

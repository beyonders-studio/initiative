/**
 * Suggestions: the published ideas on Initiative Cloud, readable signed in or
 * not. The band holds the search and the way to send feedback; the card
 * under it holds the List, by category, or the Roadmap (`#roadmap`), by
 * status. Anywhere but Cloud there is no board, and the address leads home.
 */

import { Link, Navigate, useLocation, useNavigate } from "@tanstack/react-router";
import { Search, Send } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { IdeaSort } from "@/api/generated/initiativeAPI.schemas";
import { IdeaMeta, VoteButton } from "@/components/ideas/IdeaParts";
import { useAuth } from "@/hooks/useAuth";
import { useIdeas } from "@/hooks/useIdeas";
import { useServer } from "@/hooks/useServer";
import { isCloudOrigin } from "@/lib/cloud";
import { DarkBand } from "@/pages/site/DarkBand";
import { SiteShell } from "@/pages/site/SiteShell";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { cn } from "@/ui/lib/utils";
import { LoadMore } from "@/ui/load-more";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

import { RoadmapView } from "./RoadmapView";

/** The address each view keeps, to come back to after signing in. */
const LIST_PATH = "/suggestions";
const ROADMAP_PATH = "/suggestions#roadmap";

const viewLink =
  "inline-flex min-h-9 items-center rounded-full px-3.5 font-semibold text-slate-200 text-sm hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 data-[status=active]:bg-white data-[status=active]:text-[#0b1224]";

/** List or Roadmap, as a pill on the navy band. */
const ViewSwitch = () => {
  const { t } = useTranslation("intake");
  return (
    <nav
      aria-label={t("ideas.views.label")}
      className="inline-flex gap-0.5 rounded-full border border-white/20 p-1"
    >
      <Link to="/suggestions" activeOptions={{ includeHash: true }} className={viewLink}>
        {t("ideas.views.list")}
      </Link>
      <Link
        to="/suggestions"
        hash="roadmap"
        activeOptions={{ includeHash: true }}
        className={viewLink}
      >
        {t("ideas.views.roadmap")}
      </Link>
    </nav>
  );
};

const ALL = "all";
const VOTED = "voted";
const CATEGORY = "category:";

/** A category tab: underlined in amber while chosen. */
const tab =
  "-mb-px h-auto gap-1.5 rounded-none border-transparent border-b-2 px-0 pt-3.5 pb-3 text-muted-foreground hover:bg-transparent hover:text-foreground data-[state=on]:border-amber-400 data-[state=on]:bg-transparent data-[state=on]:font-bold data-[state=on]:text-foreground";

const Count = ({ count }: { count: number }) => (
  <span className="font-medium text-muted-foreground text-xs tabular-nums">{count}</span>
);

/** The suggestions by category, most voted or newest first. */
const ListView = ({ search }: { search: string }) => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const [sort, setSort] = useState<IdeaSort>(IdeaSort.votes);
  const [statusId, setStatusId] = useState<number | null>(null);
  // All, one category, or the reader's own votes.
  const [shelf, setShelf] = useState(ALL);
  const category = shelf.startsWith(CATEGORY) ? shelf.slice(CATEGORY.length) : undefined;
  const query = useIdeas({
    search: search || undefined,
    sort,
    status_id: statusId ?? undefined,
    category,
    voted: shelf === VOTED && Boolean(user),
  });

  if (query.isError) return <Navigate to="/" replace />;
  const pages = query.data?.pages ?? [];
  const ideas = pages.flatMap((page) => page.items);
  const statuses = pages[0]?.statuses ?? [];
  const counted = pages[0]?.categories ?? [];
  // A chosen category stays offered when nothing searched for is in it.
  const categories =
    category === undefined || counted.some((each) => each.name === category)
      ? counted
      : [...counted, { name: category, count: 0 }];

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-x-6 border-b">
        <ToggleGroup
          type="single"
          aria-label={t("ideas.categoryLabel")}
          className="canvas-md:flex hidden flex-wrap justify-start gap-x-5 gap-y-0"
          value={shelf}
          onValueChange={(next) => next && setShelf(next)}
        >
          <ToggleGroupItem value={ALL} className={tab}>
            {t("ideas.allCategories")}
          </ToggleGroupItem>
          {categories.map((each) => (
            <ToggleGroupItem key={each.name} value={`${CATEGORY}${each.name}`} className={tab}>
              {each.name} <Count count={each.count} />
            </ToggleGroupItem>
          ))}
          {user ? (
            <ToggleGroupItem value={VOTED} className={tab}>
              {t("ideas.votedByMe")}
            </ToggleGroupItem>
          ) : null}
        </ToggleGroup>
        <div className="flex canvas-md:w-auto w-full flex-wrap gap-2 py-2">
          <Select value={shelf} onValueChange={setShelf}>
            <SelectTrigger
              aria-label={t("ideas.categoryLabel")}
              className="canvas-md:hidden h-11 sm:h-9"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("ideas.allCategories")}</SelectItem>
              {categories.map((each) => (
                <SelectItem key={each.name} value={`${CATEGORY}${each.name}`}>
                  <span className="inline-flex items-center gap-1.5">
                    {each.name} <Count count={each.count} />
                  </span>
                </SelectItem>
              ))}
              {user ? <SelectItem value={VOTED}>{t("ideas.votedByMe")}</SelectItem> : null}
            </SelectContent>
          </Select>
          <Select value={sort} onValueChange={(next) => setSort(next as IdeaSort)}>
            <SelectTrigger aria-label={t("ideas.sortLabel")} className="h-11 w-auto flex-1 sm:h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={IdeaSort.votes}>{t("ideas.sort.votes")}</SelectItem>
              <SelectItem value={IdeaSort.newest}>{t("ideas.sort.newest")}</SelectItem>
            </SelectContent>
          </Select>
          <Select
            value={statusId === null ? ALL : String(statusId)}
            onValueChange={(next) => setStatusId(next === ALL ? null : Number(next))}
          >
            <SelectTrigger
              aria-label={t("ideas.statusLabel")}
              className="h-11 w-auto flex-1 sm:h-9"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("ideas.anyStatus")}</SelectItem>
              {statuses.map((status) => (
                <SelectItem key={status.id} value={String(status.id)}>
                  {status.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {query.isSuccess && ideas.length === 0 ? (
        <p className="py-10 text-center text-muted-foreground">{t("ideas.none")}</p>
      ) : (
        <ul className="divide-y" aria-label={t("ideas.title")}>
          {ideas.map((idea) => (
            <li key={idea.task_id} className="flex items-center gap-4 py-5">
              <div className="min-w-0 flex-1">
                <Link
                  to="/suggestions/$taskId"
                  params={{ taskId: String(idea.task_id) }}
                  className="font-bold text-lg leading-snug hover:underline"
                >
                  {idea.title}
                </Link>
                {idea.summary ? (
                  <p className="mt-1 line-clamp-2 text-muted-foreground">{idea.summary}</p>
                ) : null}
                <div className="mt-2">
                  <IdeaMeta idea={idea} />
                </div>
              </div>
              <VoteButton idea={idea} next={LIST_PATH} size="lg" />
            </li>
          ))}
        </ul>
      )}
      <LoadMore
        hasMore={Boolean(query.hasNextPage)}
        loading={query.isFetchingNextPage}
        onLoadMore={() => void query.fetchNextPage()}
      />
    </>
  );
};

export const IdeasPage = () => {
  const { t } = useTranslation("intake");
  const { user } = useAuth();
  const { getServerOrigin } = useServer();
  const navigate = useNavigate();
  const roadmap = useLocation({ select: (location) => location.hash === "roadmap" });
  const [typed, setTyped] = useState("");
  const search = useDebouncedValue(typed.trim(), 300);

  if (!isCloudOrigin(getServerOrigin())) return <Navigate to="/" replace />;

  return (
    <SiteShell current="suggestions">
      <DarkBand stars aria-labelledby="suggestions-title">
        <div className="relative mx-auto max-w-5xl px-4 pt-10 pb-24 sm:px-8 sm:pt-18 sm:pb-28">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <h1
              id="suggestions-title"
              className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
            >
              {t("ideas.title")}
            </h1>
            <ViewSwitch />
          </div>
          <div className="mt-7 flex flex-col gap-3 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <Search
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-5 size-5 -translate-y-1/2 text-slate-700"
              />
              <Input
                type="search"
                value={typed}
                onChange={(event) => {
                  setTyped(event.target.value);
                  // What is searched for shows in the List.
                  if (roadmap) void navigate({ to: "/suggestions" });
                }}
                placeholder={t("ideas.search")}
                aria-label={t("ideas.search")}
                className="h-14 rounded-2xl border-0 bg-white pr-5 pl-13 text-base text-slate-900 shadow-lg placeholder:text-slate-500 sm:text-base"
              />
            </div>
            <Button
              size="lg"
              className="h-14 bg-amber-400 px-7 text-amber-950 text-base hover:bg-amber-300"
              asChild
            >
              <Link to="/feedback">
                <Send className="h-5 w-5" aria-hidden="true" />
                {t("ideas.sendFeedback")}
              </Link>
            </Button>
          </div>
          {user ? null : (
            <p className="mt-4 text-sm">
              <Link
                to="/login"
                search={{ next: roadmap ? ROADMAP_PATH : LIST_PATH }}
                className="font-semibold text-sky-300 hover:underline"
              >
                {t("ideas.signInToVote")}
              </Link>
            </p>
          )}
        </div>
      </DarkBand>
      <div className="mx-auto max-w-5xl px-4 pb-20 sm:px-8 sm:pb-24">
        <div
          className={cn(
            "relative -mt-12 rounded-3xl border bg-card shadow-xl",
            roadmap ? "p-3 sm:p-4" : "px-4 pb-2 sm:px-6"
          )}
        >
          {roadmap ? <RoadmapView next={ROADMAP_PATH} /> : <ListView search={search} />}
        </div>
      </div>
    </SiteShell>
  );
};

/**
 * Help: the user guide searched from inside the app, and the team asked
 * where the search did not answer it.
 *
 * Drawn once at the root by `HelpHost`, so the question mark in the sidebar,
 * the desktop title bar and every "Ask for help" button open the same panel,
 * signed in or not. It docks at the corner and leaves the page usable; on a phone it is a
 * sheet over the page. It opens on the search, with answers for the page
 * showing before anything is typed. Where the server takes help requests,
 * "Ask the team" carries the search into a request; where it gave an address
 * instead, the panel shows the address; where neither, the user guide is
 * the answer.
 *
 * What somebody writes is kept until it is sent or discarded: closing the
 * panel leaves a pill that opens it again.
 */

import { Link } from "@tanstack/react-router";
import { ArrowLeft, Check, Copy, ExternalLink, Search, X } from "lucide-react";
import { type KeyboardEvent, useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useReadHelpIndex } from "@/api/generated/help/help";
import type { HelpIndexEntry, SupportTopic } from "@/api/generated/initiativeAPI.schemas";
import {
  currentHelp,
  discardHelpDraft,
  EMPTY_DRAFT,
  type HelpDraft,
  type HelpState,
  type HelpView,
  hasDraft,
  setHelpDraft,
  updateHelp,
} from "@/components/help/helpStore";
import {
  DeviceContextFields,
  useDeviceContext,
  useRouteTemplate,
} from "@/components/tickets/DeviceContext";
import { EvidencePicker, fitToPolicy } from "@/components/tickets/Evidence";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import {
  COMMUNITY_TOPICS,
  firstLine,
  useFiledTickets,
  useFileTicket,
  useTicketAvailability,
} from "@/hooks/useTickets";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { helpSearch, pageTerms } from "@/lib/helpSearch";
import { DOCS_SITE_URL, docsUrl } from "@/lib/links";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { listFormat } from "@/ui/lib/intl";
import { useDebouncedValue } from "@/ui/lib/useDebouncedValue";
import { useFileDrop } from "@/ui/lib/useFileDrop";
import { cn } from "@/ui/lib/utils";
import { Switch } from "@/ui/switch";
import { Textarea } from "@/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** Matches the column behind it. */
const BODY_MAX = 5000;

export const HelpPanel = ({ help }: { help: HelpState }) => {
  const { user } = useAuth();
  const routeCommunityId = useActiveCommunityId();
  const communityId = help.communityId === undefined ? routeCommunityId : help.communityId;
  const availability = useTicketAvailability(communityId, { enabled: Boolean(user) });
  const support = user ? availability.data?.support : undefined;
  const canAsk = support?.mode === "form";
  const contact = support?.mode === "email" ? (support.contact ?? null) : null;
  const titleId = useId();
  // A surface may ask for the request where this server takes none: the
  // search is what is left, with the address at its foot where there is one.
  const view: HelpView = help.view === "ask" && !canAsk ? "search" : help.view;

  const close = () => updateHelp({ open: false });
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      close();
    }
  };

  return (
    <>
      {/* On a phone the panel is a sheet, and the page behind it waits. */}
      <div
        className="fixed inset-0 z-50 bg-black/50 sm:hidden"
        onClick={close}
        aria-hidden="true"
      />
      <section
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        onKeyDown={onKeyDown}
        className={cn(
          "fixed inset-x-0 bottom-0 z-50 flex h-[88dvh] flex-col rounded-t-2xl border-t bg-background pb-[env(safe-area-inset-bottom)] shadow-xl",
          "sm:inset-x-auto sm:right-4 sm:bottom-4 sm:h-[min(560px,calc(100dvh-var(--title-bar-height,0px)-2rem))] sm:w-[400px] sm:max-w-[calc(100vw-2rem)] sm:rounded-xl sm:border sm:pb-0"
        )}
      >
        {view === "search" ? (
          <SearchView
            titleId={titleId}
            query={help.query}
            communityId={communityId}
            canAsk={canAsk}
            contact={contact}
            signedIn={Boolean(user)}
            onClose={close}
          />
        ) : view === "ask" && support ? (
          <AskView
            titleId={titleId}
            draft={help.draft}
            communityId={communityId}
            topics={(support.types ?? []) as SupportTopic[]}
            policy={support.evidence}
            onClose={close}
          />
        ) : (
          <SentView titleId={titleId} onClose={close} />
        )}
      </section>
    </>
  );
};

// ---------------------------------------------------------------------------

const PanelHeader = ({
  titleId,
  title,
  onBack,
  onClose,
  children,
}: {
  titleId: string;
  title: string;
  onBack?: () => void;
  onClose: () => void;
  children?: React.ReactNode;
}) => {
  const { t } = useTranslation(["intake", "common"]);
  return (
    <div className="flex items-center gap-1 py-2 pr-2 pl-4">
      {onBack ? (
        <Button
          variant="ghost"
          size="icon-sm"
          className="-ml-2"
          onClick={onBack}
          aria-label={t("help.panel.back")}
        >
          <ArrowLeft className="size-4" />
        </Button>
      ) : null}
      <h2 id={titleId} className="flex-1 font-semibold text-sm">
        {title}
      </h2>
      {children}
      <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label={t("common:close")}>
        <X className="size-4" />
      </Button>
    </div>
  );
};

const HelpResult = ({
  entry,
  onKeyDown,
}: {
  entry: HelpIndexEntry;
  onKeyDown?: (event: KeyboardEvent<HTMLElement>) => void;
}) => (
  <a
    href={`${DOCS_SITE_URL}${entry.location}`}
    onKeyDown={onKeyDown}
    target="_blank"
    rel="noopener noreferrer"
    className="group grid gap-0.5 rounded-md p-2 hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
  >
    {entry.section ? <span className="text-muted-foreground text-xs">{entry.section}</span> : null}
    <span className="flex items-start justify-between gap-2 font-medium text-sm">
      {entry.title}
      <ExternalLink
        className="mt-1 size-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100"
        aria-hidden="true"
      />
    </span>
    {entry.snippet ? (
      <span className="line-clamp-2 text-muted-foreground text-xs">{entry.snippet}</span>
    ) : null}
  </a>
);

/** The search over the user guide, as a function of what was typed. */
const useHelpSearch = () => {
  // The index changes only with the server's version, which a reload brings.
  const { data } = useReadHelpIndex({ query: { staleTime: Number.POSITIVE_INFINITY } });
  const entries = data?.items;
  return useMemo(() => (entries?.length ? helpSearch(entries) : null), [entries]);
};

const SearchView = ({
  titleId,
  query,
  communityId,
  canAsk,
  contact,
  signedIn,
  onClose,
}: {
  titleId: string;
  query: string;
  /** The community a request asked from here is about. */
  communityId: number | null;
  canAsk: boolean;
  contact: string | null;
  signedIn: boolean;
  onClose: () => void;
}) => {
  const { t } = useTranslation(["intake", "common"]);
  const search = useHelpSearch();
  const route = useRouteTemplate();
  const results = useRef<HTMLDivElement>(null);
  const typed = query.trim();
  // Searched once typing pauses: forgiving typos costs more than a keystroke.
  const settled = useDebouncedValue(typed, 150);
  const found = useMemo(
    () => (search ? search(settled || pageTerms(route)) : []),
    [search, settled, route]
  );
  const filed = useFiledTickets({ enabled: signedIn && canAsk });
  const openRequests = (filed.data?.items ?? []).filter((item) => item.state !== "closed").length;

  // The count is said once typing pauses, not on every key.
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (!typed) return;
    const timer = setTimeout(
      () =>
        setSaid(
          found.length
            ? t("help.panel.answers", { count: found.length })
            : t("help.panel.noMatch", { query: typed })
        ),
      400
    );
    return () => clearTimeout(timer);
  }, [typed, found.length, t]);

  const step = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const links = [...(results.current?.querySelectorAll<HTMLAnchorElement>("a") ?? [])];
    if (links.length === 0) return;
    event.preventDefault();
    const at = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (event.key === "ArrowDown") links[at + 1 < links.length ? at + 1 : 0]?.focus();
    else if (at <= 0) document.getElementById("help-search")?.focus();
    else links[at - 1]?.focus();
  };

  const ask = () => {
    // What was searched starts the request, unless a draft is already there,
    // and the request stays about the community it was started in.
    const { draft } = currentHelp();
    updateHelp({
      view: "ask",
      communityId,
      draft: draft.text.trim() || !typed ? draft : { ...draft, text: typed },
    });
  };

  const copy = async () => {
    if (!contact) return;
    try {
      await navigator.clipboard.writeText(contact);
      toast.success(t("help.panel.copied"));
    } catch {
      toast.error(t("help.panel.copyFailed"));
    }
  };

  return (
    <>
      <PanelHeader titleId={titleId} title={t("common:help")} onClose={onClose} />
      {/* The user guide comes first: most people opening Help want to
          learn the app, not to search for one answer. */}
      <a
        href={docsUrl()}
        target="_blank"
        rel="noopener noreferrer"
        className="mx-4 mb-3 flex items-center gap-3 rounded-lg border bg-card p-3 transition-colors hover:bg-muted"
      >
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="font-medium text-sm">{t("help.panel.guide")}</span>
          <span className="text-muted-foreground text-xs">{t("help.panel.guideBody")}</span>
        </span>
        <ExternalLink className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      </a>
      <div className="mx-4 mb-2 flex items-center gap-2 rounded-md border bg-card px-2.5 focus-within:border-ring">
        <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          id="help-search"
          type="search"
          // biome-ignore lint/a11y/noAutofocus: the panel opens to be typed into
          autoFocus
          autoComplete="off"
          value={query}
          onChange={(event) => updateHelp({ query: event.target.value })}
          onKeyDown={step}
          aria-label={t("help.panel.search")}
          placeholder={t("help.panel.search")}
          className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      <div ref={results} className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {search === null ? (
          <p className="px-2 py-4 text-muted-foreground text-sm">{t("help.panel.unavailable")}</p>
        ) : found.length > 0 ? (
          <>
            <p className="px-2 pt-2 pb-1 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
              {typed
                ? t("help.panel.answers", { count: found.length })
                : t("help.panel.forThisPage")}
            </p>
            {found.map((entry) => (
              <HelpResult key={entry.location} entry={entry} onKeyDown={step} />
            ))}
          </>
        ) : typed ? (
          <div className="grid gap-1 px-2 py-4 text-sm">
            <p className="font-medium">{t("help.panel.noMatch", { query: typed })}</p>
            <p className="text-muted-foreground">
              {canAsk
                ? t("help.panel.noMatchAsk")
                : contact
                  ? t("help.panel.noMatchWrite")
                  : t("help.panel.noMatchBrowse")}
            </p>
          </div>
        ) : null}
      </div>
      <p className="sr-only" aria-live="polite">
        {said}
      </p>
      {canAsk ? (
        <div className="grid gap-2 border-t py-3 pr-3 pl-4">
          <span className="text-muted-foreground text-sm">{t("help.panel.noAnswer")}</span>
          <div className="flex flex-wrap items-center gap-2">
            {openRequests > 0 ? (
              <Link
                to="/my-tickets"
                onClick={onClose}
                className="text-muted-foreground text-sm underline underline-offset-2 hover:text-foreground"
              >
                {t("help.panel.openRequests", { count: openRequests })}
              </Link>
            ) : null}
            <Button className="ml-auto" onClick={ask}>
              {t("help.panel.askTeam")}
            </Button>
          </div>
        </div>
      ) : contact ? (
        <div className="grid gap-2 border-t py-3 pr-3 pl-4">
          <span className="text-muted-foreground text-sm">{t("help.panel.writeTo")}</span>
          <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2">
            <span className="min-w-0 flex-1 select-all break-all font-mono text-sm">{contact}</span>
            <Button variant="outline" size="sm" onClick={() => void copy()}>
              <Copy className="size-4" aria-hidden="true" />
              {t("common:copy")}
            </Button>
          </div>
        </div>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------

const AskView = ({
  titleId,
  draft,
  communityId,
  topics,
  policy,
  onClose,
}: {
  titleId: string;
  draft: HelpDraft;
  communityId: number | null;
  topics: SupportTopic[];
  policy: React.ComponentProps<typeof EvidencePicker>["policy"];
  onClose: () => void;
}) => {
  const { t } = useTranslation(["intake", "common"]);
  const context = useDeviceContext();
  const search = useHelpSearch();
  const [showContext, setShowContext] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // A community's own topics are asked from inside it.
  const offered = topics.filter((topic) => communityId != null || !COMMUNITY_TOPICS.has(topic));
  const topic = offered.includes(draft.topic as SupportTopic)
    ? (draft.topic as SupportTopic)
    : offered.length === 1
      ? offered[0]
      : "";
  // The answers that match what is being written stay in view; two, for the room.
  const [writing, setWriting] = useState(draft.text);
  useEffect(() => {
    const timer = setTimeout(() => setWriting(draft.text), 300);
    return () => clearTimeout(timer);
  }, [draft.text]);
  const mightAnswer = useMemo(
    () => (search && writing.trim().length >= 8 ? search(writing).slice(0, 2) : []),
    [search, writing]
  );

  const take = (incoming: File[]) => {
    if (!policy || incoming.length === 0) return;
    const { kept, dropped } = fitToPolicy([...draft.files, ...incoming], policy);
    setHelpDraft({ files: kept });
    if (dropped.length > 0) {
      toast.info(
        t("evidence.dropped", {
          count: dropped.length,
          names: listFormat(undefined, { type: "conjunction" }).format(dropped.map((f) => f.name)),
        })
      );
    }
  };
  const { dragging, handlers } = useFileDrop(Boolean(policy?.max_files), take);

  const file = useFileTicket({
    onSuccess: () =>
      updateHelp({ view: "sent", query: "", draft: EMPTY_DRAFT, communityId: undefined }),
    onError: (err) => {
      const message = getErrorMessage(err, "intake:help.error");
      if (getHttpStatus(err) === 503) setFailure(message);
      else toast.error(message);
    },
  });

  const held = !draft.text.trim()
    ? t("help.panel.needsText")
    : !topic
      ? t("help.panel.needsTopic")
      : null;
  const send = () => {
    if (held || !topic || file.isPending) return;
    const aboutCommunity = COMMUNITY_TOPICS.has(topic);
    file.mutate({
      ticket: {
        stream: "support",
        type: topic,
        community_id: aboutCommunity ? communityId : null,
        subject: firstLine(draft.text),
        body: draft.text.trim(),
        context: draft.sendContext ? context : null,
      },
      files: draft.files,
    });
  };

  return (
    <>
      <PanelHeader
        titleId={titleId}
        title={t("help.panel.askTeam")}
        onBack={() => updateHelp({ view: "search" })}
        onClose={onClose}
      />
      <div
        {...handlers}
        className="relative grid min-h-0 flex-1 content-start gap-3 overflow-y-auto px-4 pb-3"
      >
        {dragging ? (
          <div className="pointer-events-none absolute inset-1 z-10 grid place-items-center rounded-xl border-2 border-primary border-dashed bg-background/85 font-medium text-sm">
            {t("help.panel.drop")}
          </div>
        ) : null}
        <Textarea
          autoFocus
          value={draft.text}
          onChange={(event) => setHelpDraft({ text: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              send();
            }
          }}
          onPaste={(event) => {
            const pasted = Array.from(event.clipboardData.files);
            if (pasted.length > 0) {
              event.preventDefault();
              take(pasted);
            }
          }}
          aria-label={t("help.bodyLabel")}
          placeholder={t("help.bodyPlaceholder")}
          rows={6}
          maxLength={BODY_MAX}
        />
        <EvidencePicker
          policy={policy}
          files={draft.files}
          onChange={(files) => setHelpDraft({ files })}
          disabled={file.isPending}
        />
        {mightAnswer.length > 0 ? (
          <div className="grid gap-0.5 rounded-lg bg-muted p-2">
            <p className="px-2 font-semibold text-muted-foreground text-xs uppercase tracking-wide">
              {t("help.panel.mightAnswer")}
            </p>
            {mightAnswer.map((entry) => (
              <HelpResult key={entry.location} entry={entry} />
            ))}
          </div>
        ) : null}
        {offered.length > 1 ? (
          <div className="grid gap-2">
            <span id={`${titleId}-topic`} className="font-medium text-sm">
              {t("help.topicLabel")}
            </span>
            <ToggleGroup
              type="single"
              value={topic}
              onValueChange={(value) => value && setHelpDraft({ topic: value as SupportTopic })}
              aria-labelledby={`${titleId}-topic`}
              variant="outline"
              size="sm"
              className="flex-wrap justify-start"
            >
              {offered.map((value) => (
                <ToggleGroupItem key={value} value={value} className="rounded-full px-3">
                  {t(`help.topics.${value}`)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        ) : null}
        {failure ? (
          <p className="text-destructive text-sm" role="alert">
            {failure}
          </p>
        ) : null}
      </div>
      <div className="grid gap-2 border-t py-3 pr-3 pl-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs">
          <span className="min-w-0 flex-1">
            {draft.sendContext ? t("help.panel.sendsContext") : t("help.panel.sendsNoContext")}
          </span>
          <button
            type="button"
            className="underline underline-offset-2 hover:text-foreground"
            onClick={() => setShowContext((shown) => !shown)}
            aria-expanded={showContext}
          >
            {showContext ? t("help.panel.hideContext") : t("help.panel.showContext")}
          </button>
          <Switch
            checked={draft.sendContext}
            onCheckedChange={(checked) => setHelpDraft({ sendContext: checked })}
            aria-label={t("help.panel.contextSwitch")}
          />
        </div>
        {showContext ? (
          <DeviceContextFields
            context={context}
            className={cn(
              "rounded-md bg-muted p-2",
              !draft.sendContext && "line-through opacity-50"
            )}
          />
        ) : null}
        <div className="flex items-center gap-2">
          <span className="min-w-0 flex-1 text-muted-foreground text-xs">
            {held ?? t("help.panel.sendShortcut")}
          </span>
          {hasDraft(draft) ? (
            <Button variant="ghost" size="sm" onClick={discardHelpDraft}>
              {t("help.panel.discard")}
            </Button>
          ) : null}
          <Button onClick={send} disabled={Boolean(held) || file.isPending}>
            {t("help.submit")}
          </Button>
        </div>
      </div>
    </>
  );
};

// ---------------------------------------------------------------------------

const SentView = ({ titleId, onClose }: { titleId: string; onClose: () => void }) => {
  const { t } = useTranslation(["intake", "common"]);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <>
      <PanelHeader titleId={titleId} title={t("common:help")} onClose={onClose} />
      <div className="grid content-start justify-items-start gap-3 px-4 py-4" role="status">
        <span className="grid size-9 place-items-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
          <Check className="size-5" aria-hidden="true" />
        </span>
        <h3 ref={heading} tabIndex={-1} className="font-semibold outline-none">
          {t("help.panel.sent")}
        </h3>
        <p className="text-muted-foreground text-sm">{t("help.panel.sentBody")}</p>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link to="/my-tickets" onClick={onClose}>
              {t("help.panel.openTickets")}
            </Link>
          </Button>
          <Button size="sm" onClick={onClose}>
            {t("common:done")}
          </Button>
        </div>
      </div>
    </>
  );
};

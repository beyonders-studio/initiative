/**
 * Help: the user guide, searched from inside the app, and the team asked where
 * the search did not answer it.
 *
 * Drawn once at the root by `HelpHost`, so the question mark in the sidebar,
 * the desktop title bar and every "Ask for help" button open the same panel,
 * signed in or not, as a dialog over the page. It opens on the search, with
 * answers for the page showing before anything is typed. Where the server
 * takes help requests, "Ask the team" carries the search into a request; where
 * it gave an address instead, the panel shows the address.
 *
 * What somebody writes is kept until it is sent or discarded: closing Help
 * leaves a pill that opens it again.
 */

import { Link } from "@tanstack/react-router";
import { ArrowLeft, Check, ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SupportTopic } from "@/api/generated/initiativeAPI.schemas";
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
  DeviceContextSwitch,
  useDeviceContext,
  useRouteTemplate,
} from "@/components/tickets/DeviceContext";
import { TicketComposer } from "@/components/tickets/TicketComposer";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAuth } from "@/hooks/useAuth";
import { useHelpIndex } from "@/hooks/useHelpIndex";
import {
  COMMUNITY_TOPICS,
  firstLine,
  useFiledTickets,
  useFileTicket,
  useTicketAvailability,
} from "@/hooks/useTickets";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";
import { forPage, type HelpIndexEntry } from "@/lib/helpSearch";
import { DOCS_SITE_URL, docsUrl } from "@/lib/links";
import { toast } from "@/lib/mascotToast";
import { openExternal } from "@/lib/openExternal";
import { Button } from "@/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/ui/command";
import { CopyButton } from "@/ui/copy-button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/ui/dialog";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/ui/empty";
import { commandFilter } from "@/ui/lib/fuzzyMatch";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** Matches the column behind it. */
const BODY_MAX = 5000;

const close = () => updateHelp({ open: false });

export const HelpPanel = ({ help }: { help: HelpState }) => {
  const { user } = useAuth();
  const routeCommunityId = useActiveCommunityId();
  const communityId = help.communityId === undefined ? routeCommunityId : help.communityId;
  const availability = useTicketAvailability(communityId, { enabled: Boolean(user) });
  const support = user ? availability.data?.support : undefined;
  const canAsk = support?.mode === "form";
  const contact = support?.mode === "email" ? (support.contact ?? null) : null;
  // A surface may ask for the request where this server takes none: the
  // search is what is left, with the address at its foot where there is one.
  const view: HelpView = help.view === "ask" && !canAsk ? "search" : help.view;

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        aria-describedby={undefined}
        // One height for every view, so moving between them does not resize it.
        className="h-[min(36rem,calc(100dvh-2rem))] gap-0 p-0"
      >
        {view === "search" ? (
          <SearchView
            query={help.query}
            communityId={communityId}
            canAsk={canAsk}
            contact={contact}
            signedIn={Boolean(user)}
          />
        ) : view === "ask" && support ? (
          <AskView
            draft={help.draft}
            communityId={communityId}
            topics={(support.types ?? []) as SupportTopic[]}
            policy={support.evidence}
          />
        ) : (
          <SentView />
        )}
      </DialogContent>
    </Dialog>
  );
};

// ---------------------------------------------------------------------------

const PanelHeader = ({ title, onBack }: { title: string; onBack?: () => void }) => {
  const { t } = useTranslation("intake");
  return (
    <DialogHeader className="flex-row items-center gap-1 py-3 pr-12 pl-4 text-left">
      {onBack ? (
        <Button
          variant="ghost"
          size="icon-sm"
          className="-ml-2"
          onClick={onBack}
          aria-label={t("help.panel.back")}
        >
          <ArrowLeft />
        </Button>
      ) : null}
      <DialogTitle className="text-base">{title}</DialogTitle>
    </DialogHeader>
  );
};

/** One page or section of the user guide, opened outside the app. */
const HelpResult = ({ entry }: { entry: HelpIndexEntry }) => (
  <CommandItem
    value={entry.location}
    keywords={[entry.title, entry.section, entry.snippet]}
    onSelect={() => openExternal(`${DOCS_SITE_URL}${entry.location}`)}
    className="flex-col items-start gap-0.5"
  >
    {entry.section ? <span className="text-muted-foreground text-xs">{entry.section}</span> : null}
    <span className="font-medium">{entry.title}</span>
    {entry.snippet ? (
      <span className="line-clamp-2 text-muted-foreground text-xs">{entry.snippet}</span>
    ) : null}
  </CommandItem>
);

const SearchView = ({
  query,
  communityId,
  canAsk,
  contact,
  signedIn,
}: {
  query: string;
  /** The community a request asked from here is about. */
  communityId: number | null;
  canAsk: boolean;
  contact: string | null;
  signedIn: boolean;
}) => {
  const { t } = useTranslation(["intake", "common"]);
  const index = useHelpIndex();
  const entries = useMemo(() => index.data ?? [], [index.data]);
  const route = useRouteTemplate();
  const pageEntries = useMemo(() => forPage(entries, route), [entries, route]);
  const typed = query.trim();
  const filed = useFiledTickets({ enabled: signedIn && canAsk });
  const openRequests = (filed.data?.items ?? []).filter((item) => item.state !== "closed").length;

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

  return (
    <>
      <PanelHeader title={t("common:help")} />
      {/* The user guide comes first: most people opening Help want to learn
          the app, not to search for one answer. */}
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
      <Command
        filter={commandFilter}
        label={t("help.panel.search")}
        className="min-h-0 flex-1 rounded-none bg-transparent"
      >
        <CommandInput
          autoFocus
          value={query}
          onValueChange={(value) => updateHelp({ query: value })}
          placeholder={t("help.panel.search")}
        />
        <CommandList className="max-h-none flex-1 p-2">
          {index.isPending ? null : entries.length === 0 ? (
            <p className="px-2 py-6 text-center text-muted-foreground text-sm">
              {t("help.panel.unavailable")}
            </p>
          ) : typed ? (
            <>
              <CommandEmpty className="grid gap-1 px-2 py-6 text-center text-sm">
                <span className="font-medium">{t("help.panel.noMatch", { query: typed })}</span>
                <span className="text-muted-foreground">
                  {canAsk
                    ? t("help.panel.noMatchAsk")
                    : contact
                      ? t("help.panel.noMatchWrite")
                      : t("help.panel.noMatchBrowse")}
                </span>
              </CommandEmpty>
              {entries.map((entry) => (
                <HelpResult key={entry.location} entry={entry} />
              ))}
            </>
          ) : pageEntries.length > 0 ? (
            <CommandGroup heading={t("help.panel.forThisPage")}>
              {pageEntries.map((entry) => (
                <HelpResult key={entry.location} entry={entry} />
              ))}
            </CommandGroup>
          ) : null}
        </CommandList>
      </Command>
      {canAsk ? (
        <div className="grid gap-2 border-t py-3 pr-3 pl-4">
          <span className="text-muted-foreground text-sm">{t("help.panel.noAnswer")}</span>
          <div className="flex flex-wrap items-center gap-2">
            {openRequests > 0 ? (
              <Link
                to="/my-tickets"
                onClick={close}
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
            <CopyButton value={contact} label={t("common:copy")} />
          </div>
        </div>
      ) : null}
    </>
  );
};

// ---------------------------------------------------------------------------

const AskView = ({
  draft,
  communityId,
  topics,
  policy,
}: {
  draft: HelpDraft;
  communityId: number | null;
  topics: SupportTopic[];
  policy: React.ComponentProps<typeof TicketComposer>["policy"];
}) => {
  const { t } = useTranslation(["intake", "common"]);
  const context = useDeviceContext();
  const [failure, setFailure] = useState<string | null>(null);
  // A community's own topics are asked from inside it.
  const offered = topics.filter((topic) => communityId != null || !COMMUNITY_TOPICS.has(topic));
  const topic = offered.includes(draft.topic as SupportTopic)
    ? (draft.topic as SupportTopic)
    : offered.length === 1
      ? offered[0]
      : "";

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
    file.mutate({
      ticket: {
        stream: "support",
        type: topic,
        community_id: COMMUNITY_TOPICS.has(topic) ? communityId : null,
        subject: firstLine(draft.text),
        body: draft.text.trim(),
        context: draft.sendContext ? context : null,
      },
      files: draft.files,
    });
  };

  return (
    <>
      <PanelHeader title={t("help.panel.askTeam")} onBack={() => updateHelp({ view: "search" })} />
      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto px-4 pb-3">
        <TicketComposer
          autoFocus
          value={draft.text}
          onChange={(event) => setHelpDraft({ text: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              send();
            }
          }}
          aria-label={t("help.bodyLabel")}
          placeholder={t("help.bodyPlaceholder")}
          rows={6}
          maxLength={BODY_MAX}
          policy={policy}
          files={draft.files}
          onFilesChange={(files) => setHelpDraft({ files })}
          pagePicture={{ hidePeople: true }}
          disabled={file.isPending}
        />
        {offered.length > 1 ? (
          <div className="grid gap-2">
            <span id="help-topic" className="font-medium text-sm">
              {t("help.topicLabel")}
            </span>
            <ToggleGroup
              type="single"
              value={topic}
              onValueChange={(value) => value && setHelpDraft({ topic: value as SupportTopic })}
              aria-labelledby="help-topic"
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
        <DeviceContextSwitch
          context={context}
          included={draft.sendContext}
          onIncludedChange={(sendContext) => setHelpDraft({ sendContext })}
          disabled={file.isPending}
        />
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

const SentView = () => {
  const { t } = useTranslation(["intake", "common"]);
  return (
    <>
      <PanelHeader title={t("common:help")} />
      <Empty role="status" className="border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Check />
          </EmptyMedia>
          <EmptyTitle>{t("help.panel.sent")}</EmptyTitle>
          <EmptyDescription>{t("help.panel.sentBody")}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="flex-row justify-center">
          <Button variant="outline" size="sm" asChild>
            <Link to="/my-tickets" onClick={close}>
              {t("help.panel.openTickets")}
            </Link>
          </Button>
          <Button size="sm" onClick={close}>
            {t("common:done")}
          </Button>
        </EmptyContent>
      </Empty>
    </>
  );
};

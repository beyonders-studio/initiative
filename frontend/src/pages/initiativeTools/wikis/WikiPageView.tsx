import { useLocation, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { SlidersHorizontal, Sparkles } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  ContentKind,
  PropertyTarget,
  SearchEntityType,
  Tool,
  WikiPageKind,
  WikiReadingWidth,
} from "@/api/generated/initiativeAPI.schemas";
import { summarizeWikiPage } from "@/api/generated/wikis/wikis";
import { NeedAccessOr } from "@/components/access/RequestAccess";
import { type AISummary, SummarySheet } from "@/components/ai/SummarySheet";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { WikiChrome } from "@/components/initiativeTools/wikis/WikiChrome";
import {
  WikiConnectionsSheet,
  WikiPageConnections,
} from "@/components/initiativeTools/wikis/WikiPageConnections";
import { WikiPageNav } from "@/components/initiativeTools/wikis/WikiPageNav";
import { ModerationMenu } from "@/components/moderation/ModerationMenu";
import { ReportButton } from "@/components/moderation/ReportButton";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useCollaboration } from "@/hooks/useCollaboration";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useInitiative } from "@/hooks/useInitiatives";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { propertySaves } from "@/hooks/useProperties";
import { atLeast, useRegionWidthClass } from "@/hooks/useWidthClass";
import { useAddWikiPage, useUpdateWikiPage, useWiki, useWikiPage } from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { PropertiesField } from "@/lib/layouts/fieldEditors";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute, toolRouteSegment, wikiPageRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";

// The editor is the largest thing in the bundle; every other surface that
// draws one loads it on demand, and a static import here would pull it back
// into the shared chunk for all of them.
const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);

const PageBodySkeleton = () => (
  <div className="space-y-4">
    <Skeleton className="h-10 w-2/3" />
    <Skeleton className="h-4 w-full" />
    <Skeleton className="h-4 w-11/12" />
    <Skeleton className="h-4 w-4/5" />
  </div>
);

/**
 * One page of a wiki: its title, its body, and what connects to it.
 *
 * The page tree is NOT here — it has taken the sidebar (see
 * `WikiSidebarContent`), which is the whole navigation model of this tool. What
 * is here is the reading column and, beneath it, the connections: what this
 * page names, and what names it.
 *
 * The body is the same Lexical editor a native document uses, so `[[ ]]` links
 * and smart chips work exactly as they do everywhere else — and the backlinks
 * below are the edges the server reads back out of them on save.
 */
export const WikiPageView = () => {
  const { t } = useTranslation(["wikis", "common", "properties", "editor"]);
  const communityId = useActiveCommunityId();
  const gp = useCommunityPath();
  const {
    wikiId: wikiIdParam,
    pageId: pageIdParam,
    initiativeId: initiativeIdParam,
  } = useParams({ strict: false }) as {
    wikiId?: string;
    pageId?: string;
    initiativeId?: string;
  };

  // Reading or writing. Kept in the address, because the bar over the page and
  // the page's row in the tree both offer it from different React trees, and
  // because a page being edited is then a thing you can link to or reload into.
  // Reading is where everyone starts, writers included.
  const { edit } = useSearch({ strict: false }) as { edit?: true };
  const editWanted = edit === true;

  const wikiId = Number(wikiIdParam);
  const pageId = Number(pageIdParam);
  const initiativeId = Number(initiativeIdParam);
  const validIds = Number.isFinite(wikiId) && Number.isFinite(pageId);
  const pageRef = { type: SearchEntityType.wiki_page, id: pageId };

  // The newest body regardless of whether it has been sent, which is what the
  // reading view is shown the moment somebody stops writing. The server hears
  // about a body on a pause and, in a live room, writes it on a sweep of its
  // own — both of which finish long after the eye does.
  const latestBody = useRef<{ pageId: number; state: SerializedEditorState } | null>(null);
  // Live co-editing, over the same room files use — a page is just
  // another body the server keeps a Yjs document for.
  const collaboration = useCollaboration({
    socketPath: validIds
      ? `${toolRouteSegment(SearchEntityType.wiki_page)}/${pageId}/collaborate`
      : null,
    // Only while somebody is writing. A wiki is read far more than it is
    // written, so a reader opens no room and costs the server nothing.
    enabled: validIds && editWanted,
    onError: (error) => {
      toast.error(t("error"), { description: error.message });
    },
  });

  const wikiQuery = useWiki(validIds ? wikiId : null);
  const pageQuery = useWikiPage(validIds ? pageId : null);
  // `mutate` is referentially stable, so effects can depend on it without
  // re-running every render the way the mutation object would make them.
  const { mutate: savePage } = useUpdateWikiPage(wikiId, pageId);

  const canWrite = Boolean(wikiQuery.data?.can.edit);
  const initiativeQuery = useInitiative(wikiQuery.data?.initiative_id ?? null);
  const canModerate = Boolean(initiativeQuery.data?.can.moderate);
  // Editing needs both the right and the intent — somebody who may write is
  // still reading until they say otherwise.
  const isEditing = canWrite && editWanted;

  // The title is edited in place, and saved on a pause rather than on every
  // keystroke — renaming a page rewrites its slug, which is an address.
  //
  // What is being typed carries the page it is being typed INTO. Following a
  // link swaps the page under this component without remounting it, so a name
  // still waiting out its pause would otherwise be saved against whichever
  // page is open when the pause ends — the page you arrive at taking the name
  // of the page you came from.
  const [draft, setDraft] = useState<{ pageId: number; title: string } | null>(null);
  // What the server has already been told, so a pause and the blur behind it
  // do not both send the same rename. Cleared when the page changes.
  const sentTitle = useRef<string | null>(null);
  const loadedPageId = pageQuery.data?.id;
  useReadOnOpen(SearchEntityType.wiki_page, loadedPageId);
  // A wiki is read through its pages, so a page that opens opens the wiki,
  // which is the tab.
  const loadedWikiId = pageQuery.data?.wiki_id;
  useRecordOpen(Tool.wiki, loadedWikiId, { each: loadedPageId });
  useRecordOpen(ContentKind.wiki_page, loadedPageId);
  const loadedTitle = pageQuery.data?.title;
  useEffect(() => {
    sentTitle.current = null;
  }, [pageId]);
  useEffect(() => {
    if (loadedPageId === undefined) return;
    // Our own rename coming back from the server is not news, and the field
    // may have moved on since it was sent — so it is left as it is.
    if (sentTitle.current !== null && sentTitle.current === (loadedTitle ?? "")) return;
    sentTitle.current = null;
    setDraft({ pageId: loadedPageId, title: loadedTitle ?? "" });
  }, [loadedPageId, loadedTitle]);

  const debouncedDraft = useDebouncedValue(draft, 600);

  // One rename, however it is asked for — by the pause, or by leaving the
  // field, which is what a click straight into the tree does.
  const rename = useCallback(
    (pending: { pageId: number; title: string } | null) => {
      // `current` is compared, not required: a page starts with no name, and
      // naming one is the first thing anybody does to it.
      const current = pageQuery.data?.title ?? "";
      const next = pending?.title.trim() ?? "";
      if (!canWrite || !pending || pending.pageId !== pageId) return;
      if (!next || next === current || next === sentTitle.current) return;
      sentTitle.current = next;
      savePage({ title: next });
    },
    [canWrite, pageId, pageQuery.data?.title, savePage]
  );

  useEffect(() => {
    rename(debouncedDraft);
  }, [debouncedDraft, rename]);

  // What the field shows: what is being typed, or — in the moment between
  // following a link and that page arriving — the name of the page we are on.
  const draftTitle = draft?.pageId === pageId ? draft.title : (pageQuery.data?.title ?? "");

  // The editor reports every keystroke; the server hears about them 2s after
  // somebody stops, the same window a file autosaves on. Saving per change
  // would be a request per character — and each one re-reads the body for the
  // links it names.
  // The newest body, and a counter that says one arrived. The body itself is a
  // ref so a keystroke does not re-render the editor around the person typing.
  // It names its page for the same reason the title draft does: the words are
  // only ever meant for the page they were typed into.
  const pendingBody = useRef<{ pageId: number; state: SerializedEditorState } | null>(null);
  const [bodyRevision, setBodyRevision] = useState(0);
  const [writtenBody, setWrittenBody] = useState<{
    pageId: number;
    state: SerializedEditorState;
    at: number;
  } | null>(null);

  const onBodyChange = useCallback(
    (state: SerializedEditorState) => {
      if (!canWrite) return;
      pendingBody.current = { pageId, state };
      latestBody.current = { pageId, state };
      setBodyRevision((revision) => revision + 1);
    },
    [canWrite, pageId]
  );

  // A page's words never travel to another page, not even in a ref. Which
  // page they belong to is read from the address, and an address being
  // followed names no page for a moment — so this waits for the next real one
  // rather than treating that moment as a page of its own.
  const bodyOwner = useRef(pageId);
  useEffect(() => {
    if (!Number.isFinite(pageId) || bodyOwner.current === pageId) return;
    bodyOwner.current = pageId;
    pendingBody.current = null;
    latestBody.current = null;
    setWrittenBody(null);
  }, [pageId]);

  // While a room is live it owns the page's content column — it renders the
  // JSON from its Yjs state and writes both together, so the two always
  // describe the same moment. This tab stops writing over REST; with no
  // room, this is the only writer.
  const isCollaborating = collaboration.isCollaborating;
  useEffect(() => {
    if (bodyRevision === 0 || pendingBody.current === null) return;
    const timer = setTimeout(() => {
      const body = pendingBody.current;
      if (body === null) return;
      pendingBody.current = null;
      // Words left over from the page before are not this page's words, and
      // the page they were written into has been rebuilt behind us.
      if (body.pageId !== pageId || isCollaborating) return;
      savePage({ content: { ...body.state } });
    }, 2000);
    return () => clearTimeout(timer);
  }, [bodyRevision, pageId, savePage, isCollaborating]);

  // A page nobody has typed in yet is stored as `{}` — the column's default —
  // and a root with no children is the same thing said differently. Lexical
  // refuses either as a starting state, so both are handed over as "no state"
  // and it builds its own empty document.
  const servedBody = useMemo(() => {
    const stored = pageQuery.data?.content as SerializedEditorState | undefined;
    const children = stored?.root?.children;
    return Array.isArray(children) && children.length > 0 ? stored : null;
  }, [pageQuery.data?.content]);

  const wiki = wikiQuery.data;
  const page = pageQuery.data;

  // Putting the eye back on. What was just typed is kept for the reading view,
  // and what has not been sent is sent now rather than waiting out a pause
  // nobody is going to finish — otherwise the page is read back as it was
  // before the edit, or as nothing at all if it had never been written to.
  const wasEditing = useRef(false);
  useEffect(() => {
    if (!validIds) return;
    if (isEditing) {
      wasEditing.current = true;
      return;
    }
    if (!wasEditing.current) return;
    wasEditing.current = false;

    const written = latestBody.current;
    if (!written || written.pageId !== pageId) return;
    setWrittenBody({ ...written, at: Date.now() });

    const unsent = pendingBody.current;
    if (!unsent || unsent.pageId !== pageId) return;
    pendingBody.current = null;
    if (isCollaborating) return;
    savePage({ content: { ...unsent.state } });
  }, [isEditing, validIds, pageId, isCollaborating, savePage]);

  // What the editor is handed, and a token that changes with it.
  //
  // Lexical reads its starting state ONCE, at mount, so a body that arrives
  // later — the save that just landed, the page you clicked — only reaches the
  // screen if the editor is rebuilt for it. The token is part of the reading
  // key alone: rebuilding the editor somebody is typing in would take their
  // cursor with it.
  const ownBody = writtenBody?.pageId === pageId ? writtenBody : null;
  const body = ownBody?.state ?? servedBody;
  const bodyToken = ownBody ? `own:${ownBody.at}` : `served:${page?.updated_at ?? "none"}`;

  // Arriving at a heading. The editor stamps each heading's anchor on the
  // element as it renders, so this waits for the body to be on screen rather
  // than firing on navigation — a page opened from a heading in the sidebar is
  // usually being fetched at the moment the link is followed.
  const hash = useLocation({ select: (location) => location.hash });
  useEffect(() => {
    if (!hash || !page) return;
    let cancelled = false;
    const find = () => {
      if (cancelled) return;
      const heading = document.getElementById(hash);
      if (heading) heading.scrollIntoView({ behavior: "smooth", block: "start" });
      else requestAnimationFrame(find);
    };
    requestAnimationFrame(find);
    return () => {
      cancelled = true;
    };
  }, [hash, page]);

  // The conversation is a drawer: a wiki is browsed, and talking about a page
  // is a different activity from reading it.
  const [commentsOpen, setCommentsOpen] = useState(false);
  const { isEnabled: aiEnabled } = useAIEnabled();
  const [summaryOpen, setSummaryOpen] = useState(false);
  // One page's summary; reading another page starts afresh.
  const [summary, setSummary] = useState<{ pageId: number; written: AISummary } | null>(null);
  // A page's properties are about the page rather than part of reading it, so
  // they wait in a drawer of their own too.
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  // Reading or writing. Kept in the address, because the bar over the page and
  // the page's row in the tree both offer it from different React trees, and
  // because a page being edited is then a thing you can link to or reload into.
  // Reading is where everyone starts, writers included.

  // Whether there is gutter to put the rail in: the row the words and the
  // rail share, which opening the rail does not resize.
  const [row, setRow] = useState<HTMLDivElement | null>(null);
  const railFitsBeside = atLeast(useRegionWidthClass(row), "md");
  // Whether the connections rail is showing. A per-visit choice: it is
  // reading furniture, not a setting.
  const [showConnections, setShowConnections] = useState(true);
  // Whether the rail was asked for out loud. Beside the words it is furniture
  // and can simply be there; over them it is an interruption, so a narrow
  // screen waits to be asked rather than opening a drawer on arrival.
  const [railAsked, setRailAsked] = useState(false);

  const createPage = useAddWikiPage(wikiId, initiativeId);
  const navigate = useNavigate();
  const addPage = () => createPage.mutate({});

  // The screen's primary create action is a page, not another wiki — this is
  // the inside of one.
  useRegisterPrimaryCreateAction(canWrite ? { run: addPage, label: t("pages.newPage") } : null);

  if (!validIds || pageQuery.isError) {
    return (
      <NeedAccessOr
        error={pageQuery.error}
        entity={validIds ? { kind: "wiki_page", id: pageId } : undefined}
      >
        <Card className="mx-auto mt-10 max-w-md">
          <CardHeader>
            <CardTitle>{t("pages.notFound")}</CardTitle>
          </CardHeader>
        </Card>
      </NeedAccessOr>
    );
  }

  // The wiki is what the chrome is made of, and it is cached across every page
  // in it — so only the first arrival waits. After that the chrome stays put
  // and the column beneath it is what changes, which is what stops a click on
  // a page from blanking the screen and the sidebar with it.
  if (!wiki) {
    return <p className="p-6 text-muted-foreground text-sm">{t("pages.loading")}</p>;
  }

  const isComfortable = wiki.reading_width === WikiReadingWidth.comfortable;
  // Asked for, allowed by the wiki, and there is a page to have connections.
  const railOpen = showConnections && wiki.show_connections && Boolean(page);
  const sheetOpen = railOpen && !railFitsBeside && railAsked;
  // What the toggle shows is what is on screen: beside the words the rail is
  // there from the start, while a drawer is shut until it is asked for.
  const connectionsShown = railFitsBeside ? showConnections : sheetOpen;
  // Definitions belong to an initiative, so a community-level wiki's pages have
  // none; and a reader has nothing to open on a page that carries none.
  const propertiesInitiativeId = wiki.initiative_id;
  const offersProperties =
    propertiesInitiativeId !== null &&
    Boolean(page) &&
    (canWrite || Boolean(page?.properties.length));

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <WikiChrome
          wiki={wiki}
          pageTitle={isEditing ? draftTitle : page?.title || t("common:untitled")}
          pageId={page?.id}
          onRename={isEditing ? (value) => setDraft({ pageId, title: value }) : undefined}
          // Leaving the field sends the name now. Clicking a page in the tree
          // blurs before it navigates, so a rename typed and immediately
          // walked away from lands on the page it was typed into.
          onRenameCommit={isEditing ? () => rename(draft) : undefined}
          pageUpdatedAt={page?.updated_at}
          canWrite={canWrite}
          editing={isEditing}
          isDraft={page?.is_draft ?? false}
          onPublish={() =>
            savePage({ is_draft: false }, { onSuccess: () => toast.success(t("page.published")) })
          }
          onToggleEditing={() =>
            void navigate({
              to: gp(wikiPageRoute(initiativeId, wikiId, pageId)),
              search: isEditing ? {} : { edit: true },
              replace: true,
            })
          }
          onOpenComments={() => setCommentsOpen(true)}
          onToggleConnections={() => {
            setRailAsked(true);
            setShowConnections(!connectionsShown);
          }}
          connectionsOpen={connectionsShown}
          trailing={
            <>
              {offersProperties ? (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      onClick={() => setPropertiesOpen(true)}
                      aria-label={t("properties:title")}
                    >
                      <SlidersHorizontal className="size-4" aria-hidden />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{t("properties:title")}</TooltipContent>
                </Tooltip>
              ) : null}
              {page && page.id === pageId && page.kind === WikiPageKind.page ? (
                <>
                  {aiEnabled ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-8"
                          onClick={() => setSummaryOpen(true)}
                          aria-label={t("editor:summary.title")}
                        >
                          <Sparkles className="size-4" aria-hidden />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>{t("editor:summary.title")}</TooltipContent>
                    </Tooltip>
                  ) : null}
                  <ReportButton
                    targetType={SearchEntityType.wiki_page}
                    targetId={page.id}
                    authorId={page.created_by}
                    className="size-8"
                  />
                  {/* Taken down or held, the page is gone, so the reader is
                      put back at the wiki's front page. */}
                  <ModerationMenu
                    targetType={SearchEntityType.wiki_page}
                    targetId={page.id}
                    canModerate={canModerate}
                    communityId={page.community_id}
                    className="size-8"
                    onGone={() =>
                      void navigate({
                        to: gp(toolDetailRoute(Tool.wiki, wiki.initiative_id, wikiId)),
                      })
                    }
                  />
                </>
              ) : null}
            </>
          }
        />

        <div ref={setRow} className="flex min-h-0 flex-1">
          {/* Read, the page scrolls here. Written, the editor is the height
              of what is left and scrolls itself, the way a document's does, so
              its toolbar stays in reach however long the page runs. */}
          <div
            className={cn(
              "min-w-0 flex-1",
              isEditing ? "flex flex-col overflow-hidden" : "overflow-y-auto"
            )}
          >
            {/* The measure. The surface is the window; the words are not, so
                the column is centred in whatever space is left and capped at a
                line length somebody can actually read. Capping it is also what
                keeps the rail from moving the text: on a wide screen the rail
                takes gutter, and the column does not shift at all. */}
            <div
              className={cn(
                "mx-auto w-full px-6 py-8 md:px-10",
                isComfortable ? "max-w-3xl" : "max-w-6xl",
                isEditing && "flex min-h-0 flex-1 flex-col"
              )}
            >
              {/* The row has to BE this page: a body from the page before it
                  is not this page's body, however briefly it is held. */}
              {page && page.id === pageId ? (
                <>
                  <Suspense fallback={<PageBodySkeleton />}>
                    <Editor
                      // Rebuilt rather than switched: the editor captures
                      // whether it is collaborative at first mount and never
                      // re-reads it, so flipping that on a live instance is
                      // outside its contract. Changing the key hands it a fresh
                      // one for the mode being entered.
                      key={`${pageId}:${isEditing ? "edit" : `read:${bodyToken}`}`}
                      editorSerializedState={body ?? undefined}
                      onSerializedChange={onBodyChange}
                      readOnly={!isEditing}
                      showToolbar={isEditing}
                      // Reading a wiki is reading a web page, so the sheet a
                      // document draws itself comes off. Wiki-local: the class
                      // overrides the variant here and changes nothing about how
                      // a document renders.
                      className={cn(
                        isEditing
                          ? "min-h-0 flex-1"
                          : "rounded-none border-0 bg-transparent shadow-none"
                      )}
                      collaborative={collaboration.isReady}
                      providerFactory={collaboration.providerFactory}
                      // Always on, so the body the room is handed stays current
                      // between sweeps for anyone reading it over REST.
                      trackChanges
                      hasSynced={collaboration.hasSynced}
                      initiativeId={Number.isFinite(initiativeId) ? initiativeId : null}
                      subject={`wiki_page:${pageId}`}
                      supportsEntityMentions
                      // Being read, the body has no sheet of its own and the
                      // reading column is its gutter. Being written, it is back
                      // inside a bordered editor, and words against that border
                      // are words with no margin — so it takes the same gutter a
                      // document's editor does.
                      compact={!isEditing}
                    />
                  </Suspense>
                  {/* Where to go from here. Reading furniture: somebody who is
                      writing is not looking for the way out of the page. */}
                  {isEditing ? null : (
                    <WikiPageNav wikiId={wikiId} initiativeId={initiativeId} currentId={pageId} />
                  )}
                </>
              ) : (
                <PageBodySkeleton />
              )}
            </div>
          </div>

          {/* The rail: where this page leads. The contents of the page itself
              are in the sidebar, under the page — one outline, in the column
              that already carries the navigation.

              Beside the words when there is gutter for it, which is the width
              at which opening it moves nothing. */}
          {railOpen && railFitsBeside ? (
            <div className="flex w-72 shrink-0 flex-col overflow-y-auto py-6 pr-6">
              <WikiPageConnections entity={pageRef} initiativeId={wiki.initiative_id} />
            </div>
          ) : null}
        </div>
      </div>

      {/* Too narrow to sit beside the words, so it opens over them instead —
          the control means the same thing at every width. */}
      <WikiConnectionsSheet
        entity={pageRef}
        initiativeId={wiki.initiative_id}
        open={sheetOpen}
        onOpenChange={(open) => !open && setShowConnections(false)}
      />

      <Sheet open={propertiesOpen && offersProperties} onOpenChange={setPropertiesOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-md">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle>{t("properties:title")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {page && propertiesInitiativeId !== null ? (
              <PropertiesField
                kind={propertySaves[PropertyTarget.wiki_page]}
                id={page.id}
                properties={page.properties ?? []}
                readOnly={!canWrite}
                initiativeId={propertiesInitiativeId}
                canOpen={{ tool: Tool.wiki, id: wikiId }}
                hideLabel
              />
            ) : null}
          </div>
        </SheetContent>
      </Sheet>

      <SummarySheet
        open={summaryOpen}
        onOpenChange={setSummaryOpen}
        request={(options, signal) => summarizeWikiPage(communityId, pageId, options, signal)}
        summary={summary?.pageId === pageId ? summary.written : null}
        onSummaryChange={(written) => setSummary(written ? { pageId, written } : null)}
      />

      {/* Hidden until asked for: browsing a wiki is reading it, and the
          conversation about it is a different activity. */}
      <Sheet open={commentsOpen} onOpenChange={setCommentsOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle className="sr-only">{t("comments")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {/* The page's thread, not the wiki's: a note about the rota
                belongs on the rota. The wiki still answers for whether there
                is one at all, and for who may read it. */}
            <ToolCommentsPanel
              tool={Tool.wiki}
              entity={wiki}
              target={{ type: SearchEntityType.wiki_page, id: pageId }}
            />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};

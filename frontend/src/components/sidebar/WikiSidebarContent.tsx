import { Link } from "@tanstack/react-router";
import {
  ChevronLeft,
  ChevronsDownUp,
  ChevronsUpDown,
  FilePlus,
  Search,
  Settings,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool, WikiPageKind, type WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { FileChooserDialog } from "@/components/files/FileChooserDialog";
import { WikiPageActions } from "@/components/initiativeTools/wikis/WikiPageActions";
import {
  useWikiTreeExpansion,
  WikiPageTree,
} from "@/components/initiativeTools/wikis/WikiPageTree";
import { SubscribeButton } from "@/components/SubscribeButton";
import { Button } from "@/components/ui/button";
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  useAddWikiFile,
  useAddWikiPage,
  useMoveWikiFile,
  useMoveWikiPage,
  useRemoveWikiFile,
  useWiki,
  useWikiPages,
} from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { TOOL_ICONS, toolSettingsRoute, wikiFileRoute, wikiPageRoute } from "@/lib/tools";

// Adding a file to a wiki is named by the files tool itself, so the row
// says which tool it reaches into rather than inventing a second mark for it.
const FileIcon = TOOL_ICONS[Tool.file];

interface WikiSidebarContentProps {
  wikiId: number;
  initiativeId: number;
  /** The page the reader is on, so the tree marks it. */
  activePageId?: number | null;
  /** Climbs back out to the ordinary navigation. */
  onBack: () => void;
}

/**
 * A wiki's pages, in the column the navigation was in.
 *
 * A wiki is a list of pages and then one of them, which is two levels in a
 * place that has room for one. So opening a wiki drills, exactly as My
 * Messages does: the page tree takes the sidebar and the arrow in the header
 * climbs back out.
 *
 * The tree is the navigation here — not a panel beside the text — because that
 * is what separates a wiki from a folder of files: you read it by moving
 * around it, and the shape has to be in front of you the whole time.
 */
export const WikiSidebarContent = ({
  wikiId,
  initiativeId,
  activePageId,
  onBack,
}: WikiSidebarContentProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useCommunityPath();

  const wikiQuery = useWiki(wikiId);
  const pagesQuery = useWikiPages(wikiId);
  const createPage = useAddWikiPage(wikiId, initiativeId);
  // Putting a file in the wiki, and taking one back out.
  const [addingFile, setAddingFile] = useState(false);
  const addFile = useAddWikiFile(wikiId, {
    onSuccess: () => {
      toast.success(t("files.added"));
      setAddingFile(false);
    },
  });
  const removeFile = useRemoveWikiFile(wikiId);
  const movePage = useMoveWikiPage(wikiId);
  const moveFile = useMoveWikiFile(wikiId);

  const pages = pagesQuery.data?.items ?? [];
  // A file already in the wiki is not offered again.
  const filed = useMemo(
    () => new Set(pages.filter((page) => page.kind === WikiPageKind.file).map((page) => page.id)),
    [pages]
  );

  // Which rows are open. Held here rather than inside the tree because the
  // button over it acts on the same set the rows do.
  const expansion = useWikiTreeExpansion(pages);

  // Searching a wiki is finding a page in it, so this filters the tree rather
  // than opening the palette: the answer is a list of pages, and the list is
  // already on screen.
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const matches = useMemo(
    () => (needle ? pages.filter((page) => page.title.toLowerCase().includes(needle)) : []),
    [pages, needle]
  );
  // Writing is the wiki's own gate, so the add affordances appear exactly
  // where the server would accept one.
  const canWrite = Boolean(wikiQuery.data?.can.edit);

  const addPage = () => createPage.mutate({});

  // A drop tells the server where the page landed; the tree is then redrawn
  // from what comes back rather than from what the drag guessed.
  const movePageTo = (page: WikiPageSummary, parentPageId: number | null, position: number) => {
    // Both kinds of row sit in one tree; which endpoint keeps their place is
    // the only thing that differs, because a file's place belongs to the
    // wiki rather than to the file.
    if (page.kind === WikiPageKind.file) {
      moveFile.mutate({ fileId: page.id, parent_page_id: parentPageId, position });
    } else {
      movePage.mutate({ pageId: page.id, parent_page_id: parentPageId, position });
    }
  };

  return (
    <>
      <SidebarHeader
        className="gap-0 border-b p-0"
        style={{ paddingTop: "var(--safe-area-inset-top)" }}
      >
        <div className="flex h-12 min-w-0 items-center gap-1 px-1.5">
          <Button variant="ghost" size="icon" className="size-8 shrink-0" onClick={onBack}>
            <ChevronLeft className="size-4" aria-hidden />
            <span className="sr-only">{t("backToWikis")}</span>
          </Button>
          <h2 className="min-w-0 flex-1 truncate font-semibold text-lg">
            {wikiQuery.data?.name ?? t("title")}
          </h2>
          <SubscribeButton kind={Tool.wiki} entityId={wikiId} className="size-8" />
          {canWrite ? (
            <Button variant="ghost" size="icon" className="size-8 shrink-0" asChild>
              <Link to={gp(toolSettingsRoute(Tool.wiki, initiativeId, wikiId))}>
                <Settings className="size-4" aria-hidden />
                <span className="sr-only">{t("settings.title")}</span>
              </Link>
            </Button>
          ) : null}
        </div>
      </SidebarHeader>

      <div className="relative border-b">
        <Search
          className="pointer-events-none absolute top-2.5 left-4 size-4 text-muted-foreground"
          aria-hidden
        />
        <SidebarInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("pages.searchPlaceholder")}
          aria-label={t("pages.search")}
          className="h-9 border-0 bg-transparent pl-9 shadow-none focus-visible:ring-0"
        />
      </div>

      <SidebarContent className="h-full overflow-y-auto overflow-x-hidden">
        <SidebarGroup>
          {pagesQuery.isLoading ? (
            <p className="px-2 py-1.5 text-muted-foreground text-sm">{t("pages.loading")}</p>
          ) : needle ? (
            matches.length === 0 ? (
              <p className="px-2 py-1.5 text-muted-foreground text-sm">
                {t("pages.searchEmpty", { query: query.trim() })}
              </p>
            ) : (
              <SidebarMenu>
                {matches.map((page) => (
                  <SidebarMenuItem key={page.id}>
                    <SidebarMenuButton asChild size="sm" isActive={page.id === activePageId}>
                      <Link
                        to={gp(
                          page.kind === WikiPageKind.file
                            ? wikiFileRoute(initiativeId, wikiId, page.id)
                            : wikiPageRoute(initiativeId, wikiId, page.id)
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate">
                          {page.title || t("common:untitled")}
                        </span>
                      </Link>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            )
          ) : (
            <>
              {/* The tree's own heading, and the control that opens or closes
                  all of it — the same pairing the app's sidebar uses over its
                  initiatives and its tags. */}
              <SidebarGroupLabel className="flex items-center gap-2 py-2">
                <span className="flex-1">{t("pages.groupLabel")}</span>
                {!expansion.isEmpty && (
                  <Tooltip delayDuration={300}>
                    <TooltipTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-5 w-5 shrink-0"
                        onClick={expansion.toggleAll}
                        aria-label={
                          expansion.allOpen ? t("pages.collapseAll") : t("pages.expandAll")
                        }
                      >
                        {expansion.allOpen ? (
                          <ChevronsDownUp className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronsUpDown className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="bottom">
                      <p>{expansion.allOpen ? t("pages.collapseAll") : t("pages.expandAll")}</p>
                    </TooltipContent>
                  </Tooltip>
                )}
              </SidebarGroupLabel>
              <WikiPageTree
                pages={pages}
                activePageId={activePageId}
                homePageId={wikiQuery.data?.home_page_id}
                hrefOf={(page) =>
                  gp(
                    page.kind === WikiPageKind.file
                      ? wikiFileRoute(initiativeId, wikiId, page.id)
                      : wikiPageRoute(initiativeId, wikiId, page.id)
                  )
                }
                expansion={expansion}
                onMove={canWrite ? movePageTo : undefined}
                renderRowMenu={
                  canWrite && wikiQuery.data
                    ? (page) => (
                        <WikiPageActions
                          wiki={wikiQuery.data}
                          page={page}
                          canWrite={canWrite}
                          initiativeId={initiativeId}
                          onRemoveFile={() =>
                            removeFile.mutate(page.id, {
                              onSuccess: () => toast.success(t("files.removed")),
                            })
                          }
                        />
                      )
                    : undefined
                }
                accentColor={wikiQuery.data?.accent_color}
              />
              {canWrite ? (
                <SidebarMenu>
                  <SidebarMenuItem>
                    <SidebarMenuButton
                      size="sm"
                      onClick={() => addPage()}
                      disabled={createPage.isPending}
                    >
                      <FilePlus className="h-4 w-4" />
                      <span>{t("pages.newPage")}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                  <SidebarMenuItem>
                    <SidebarMenuButton size="sm" onClick={() => setAddingFile(true)}>
                      <FileIcon className="h-4 w-4" />
                      <span>{t("files.addFile")}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                </SidebarMenu>
              ) : null}
            </>
          )}
        </SidebarGroup>
      </SidebarContent>

      <FileChooserDialog
        initiativeId={initiativeId}
        exclude={filed}
        open={addingFile}
        onOpenChange={setAddingFile}
        onPick={(fileId) => addFile.mutate(fileId)}
        pending={addFile.isPending}
        text={{ title: t("files.addFile"), description: t("files.pick"), none: t("files.none") }}
      />
    </>
  );
};

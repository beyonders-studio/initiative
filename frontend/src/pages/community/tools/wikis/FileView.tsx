import { Link, useLocation } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  SearchEntityType,
  Tool,
  WikiPageKind,
  WikiReadingWidth,
} from "@/api/generated/initiativeAPI.schemas";
import { NeedAccessOr } from "@/components/access/RequestAccess";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { isWideFile, ReadOnlyFileBody } from "@/components/tools/files/detail/ReadOnlyFileBody";
import { useFile } from "@/hooks/useFiles";
import { useRouteId } from "@/hooks/useRouteId";
import { useWiki } from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolDetailRoute } from "@/lib/tools";
import { WikiChrome } from "@/pages/community/tools/wikis/WikiChrome";
import {
  WikiConnectionsSheet,
  WikiPageConnections,
} from "@/pages/community/tools/wikis/WikiPageConnections";
import { WikiPageNav } from "@/pages/community/tools/wikis/WikiPageNav";
import { Button } from "@/ui/button";
import { Card, CardHeader, CardTitle } from "@/ui/card";
import { atLeast, useRegionWidthClass } from "@/ui/lib/useWidthClass";
import { cn } from "@/ui/lib/utils";
import { EditorSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/ui/sheet";
import { Skeleton } from "@/ui/skeleton";

/**
 * A file, read as a page of the wiki it was put in.
 *
 * The same chrome and the same column a page of the wiki's own gets, because
 * that is the point of putting it here — it is read with the wiki's navigation
 * beside it rather than as a detour out of one.
 *
 * It is never editable here. A file in a wiki is still that file: it
 * has its own address, its own sharing and its own history, and writing it
 * happens there. So the writing control leaves rather than switching a mode,
 * and nothing on this screen can change what is written.
 */
export const FileView = () => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useCommunityPath();
  const wikiId = useRouteId("wikiId");
  const fileId = useRouteId("fileId");
  const initiativeId = useRouteId("initiativeId");

  const wikiQuery = useWiki(wikiId);
  const fileQuery = useFile(fileId);

  const wiki = wikiQuery.data;
  const file = fileQuery.data;

  const [commentsOpen, setCommentsOpen] = useState(false);
  const [showConnections, setShowConnections] = useState(true);
  const [railAsked, setRailAsked] = useState(false);
  const [row, setRow] = useState<HTMLDivElement | null>(null);
  const railFitsBeside = atLeast(useRegionWidthClass(row), "md");

  // Arriving at a heading, the same way a page of the wiki's own does.
  const hash = useLocation({ select: (location) => location.hash });
  useEffect(() => {
    if (!hash || !file) return;
    let cancelled = false;
    const find = () => {
      if (cancelled) return;
      const heading = window.document.getElementById(hash);
      if (heading) heading.scrollIntoView({ behavior: "smooth", block: "start" });
      else requestAnimationFrame(find);
    };
    requestAnimationFrame(find);
    return () => {
      cancelled = true;
    };
  }, [hash, file]);

  if (wikiId === null || fileId === null || initiativeId === null || fileQuery.isError) {
    return (
      <NeedAccessOr
        error={fileQuery.error}
        entity={fileId === null ? undefined : { kind: "file", id: fileId }}
      >
        <Card className="mx-auto mt-10 max-w-md">
          <CardHeader>
            <CardTitle>{t("pages.notFound")}</CardTitle>
          </CardHeader>
        </Card>
      </NeedAccessOr>
    );
  }

  if (!wiki) {
    return (
      <SkeletonRegion className="p-6">
        <EditorSkeleton />
      </SkeletonRegion>
    );
  }

  const fileRef = { type: SearchEntityType.file, id: fileId };

  // Prose keeps the wiki's reading width; a file, a canvas or a grid needs
  // the room.
  const isComfortable = wiki.reading_width === WikiReadingWidth.comfortable && !isWideFile(file);
  const railOpen = showConnections && wiki.show_connections && Boolean(file);
  const sheetOpen = railOpen && !railFitsBeside && railAsked;
  // What the toggle shows is what is on screen: beside the words the rail is
  // there from the start, while a drawer is shut until it is asked for.
  const connectionsShown = railFitsBeside ? showConnections : sheetOpen;

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <WikiChrome
          wiki={wiki}
          pageTitle={file?.name || t("common:untitled")}
          pageUpdatedAt={file?.updated_at}
          // Writing happens where the file lives, so this screen offers no
          // mode to enter.
          canWrite={false}
          editing={false}
          onToggleEditing={() => {}}
          onOpenComments={() => setCommentsOpen(true)}
          commentsEnabled={file?.comments_enabled ?? false}
          onToggleConnections={() => {
            setRailAsked(true);
            setShowConnections(!connectionsShown);
          }}
          connectionsOpen={connectionsShown}
          trailing={
            <Button variant="outline" size="sm" className="h-8" asChild>
              <Link to={gp(toolDetailRoute(Tool.file, initiativeId, fileId))}>
                {t("files.openFile")}
              </Link>
            </Button>
          }
        />

        <div ref={setRow} className="flex min-h-0 flex-1">
          <div className="min-w-0 flex-1 overflow-y-auto">
            <div
              className={cn(
                "mx-auto w-full px-6 py-8 md:px-10",
                isComfortable ? "max-w-3xl" : "max-w-6xl"
              )}
            >
              {/* A copy cached from an earlier visit can predate the last save,
                  and a spreadsheet or a canvas reads its content once — so the
                  body waits for this visit's own fetch. */}
              {file && fileQuery.isFetchedAfterMount ? (
                <>
                  <ReadOnlyFileBody
                    file={file}
                    // Prose runs on in the wiki's own column rather than in a card.
                    className={
                      isWideFile(file)
                        ? undefined
                        : "max-h-none rounded-none border-0 bg-transparent shadow-none"
                    }
                  />
                  {/* A borrowed file is a page of this wiki while you are
                      reading it here, so it leads on like one. */}
                  <WikiPageNav
                    wikiId={wikiId}
                    initiativeId={initiativeId}
                    currentId={fileId}
                    currentKind={WikiPageKind.file}
                  />
                </>
              ) : (
                <div className="space-y-4">
                  <Skeleton className="h-4 w-full" />
                  <Skeleton className="h-4 w-11/12" />
                  <Skeleton className="h-4 w-4/5" />
                </div>
              )}
            </div>
          </div>

          {railOpen && railFitsBeside ? (
            <div className="flex w-72 shrink-0 flex-col overflow-y-auto py-6 pr-6">
              <WikiPageConnections entity={fileRef} initiativeId={wiki.initiative_id} />
            </div>
          ) : null}
        </div>
      </div>

      <WikiConnectionsSheet
        entity={fileRef}
        initiativeId={wiki.initiative_id}
        open={sheetOpen}
        onOpenChange={(open) => !open && setShowConnections(false)}
      />

      <Sheet open={commentsOpen} onOpenChange={setCommentsOpen}>
        <SheetContent side="right" className="flex w-full flex-col gap-0 p-0 sm:max-w-lg">
          <SheetHeader className="border-b px-5 py-4">
            <SheetTitle className="sr-only">{t("comments")}</SheetTitle>
          </SheetHeader>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {/* A file in a wiki is still that file — its thread is
                its own, and is the same one its detail page shows. */}
            {file ? <ToolCommentsPanel tool={Tool.file} entity={file} /> : null}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
};

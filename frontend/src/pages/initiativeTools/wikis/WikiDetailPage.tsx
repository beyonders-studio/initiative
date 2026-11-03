import { Navigate, useParams } from "@tanstack/react-router";
import { BookText, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { WikiPageTree } from "@/components/initiativeTools/wikis/WikiPageTree";
import { useRegisterPrimaryCreateAction } from "@/components/navigation/CreateActionContext";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useAddWikiPage, useWiki, useWikiPages } from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { toolListRoute, wikiPageRoute } from "@/lib/tools";

/**
 * A wiki, opened.
 *
 * There is deliberately no landing screen of its own when the wiki has pages:
 * a wiki IS its pages, so this sends the reader to the home page — the one
 * somebody nominated, or failing that the first — and the page view takes it
 * from there. What is left here is the case that screen could not serve: a
 * wiki with nothing written in it yet.
 */
export const WikiDetailPage = () => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useCommunityPath();
  const { wikiId: wikiIdParam, initiativeId: initiativeIdParam } = useParams({
    strict: false,
  }) as { wikiId?: string; initiativeId?: string };

  const wikiId = Number(wikiIdParam);
  const initiativeId = Number(initiativeIdParam);
  const validIds = Number.isFinite(wikiId) && Number.isFinite(initiativeId);

  const wikiQuery = useWiki(validIds ? wikiId : null);
  const pagesQuery = useWikiPages(validIds ? wikiId : null);
  useReadOnOpen(Tool.wiki, wikiQuery.data?.id);
  const createPage = useAddWikiPage(wikiId, initiativeId);

  const pages = pagesQuery.data?.items ?? [];
  const addPage = () => createPage.mutate({});

  const canWrite = Boolean(wikiQuery.data?.can.edit);

  // Inside a wiki, the thing to create is a page. Without this the button in
  // the corner keeps whatever the list before it registered — a second wiki.
  useRegisterPrimaryCreateAction(canWrite ? { run: addPage, label: t("pages.newPage") } : null);

  if (!validIds || wikiQuery.isError) {
    return (
      <ToolAccessStatus
        error={wikiQuery.error}
        keys="wikis:"
        backTo={gp(toolListRoute(Tool.wiki, initiativeId))}
        backLabel={t("backToWikis")}
        entity={validIds ? { kind: "wiki", id: wikiId } : undefined}
      />
    );
  }

  if (wikiQuery.isLoading || pagesQuery.isLoading) {
    return <p className="p-6 text-muted-foreground text-sm">{t("loading")}</p>;
  }

  // The home page if one was nominated, else the first page in reading order.
  const landing =
    pages.find((page) => page.id === wikiQuery.data?.home_page_id) ?? pages.at(0) ?? null;

  if (landing) {
    return <Navigate to={gp(wikiPageRoute(initiativeId, wikiId, landing.id))} replace />;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
              <BookText className="size-5" aria-hidden />
            </span>
            <div>
              <CardTitle>{t("pages.empty")}</CardTitle>
              <CardDescription>{t("pages.emptyDescription")}</CardDescription>
            </div>
          </div>
        </CardHeader>
        {canWrite ? (
          <CardContent>
            <Button onClick={addPage} disabled={createPage.isPending}>
              <Plus className="size-4" aria-hidden />
              {t("pages.createFirst")}
            </Button>
          </CardContent>
        ) : null}
      </Card>

      {/* Nothing to draw yet, but the tree is what this screen becomes — it is
          rendered so the empty state and the filled one are the same layout. */}
      <WikiPageTree
        pages={pages}
        homePageId={wikiQuery.data?.home_page_id}
        hrefOf={(page) => gp(wikiPageRoute(initiativeId, wikiId, page.id))}
      />
    </div>
  );
};

import { Link, useNavigate } from "@tanstack/react-router";
import {
  Check,
  Copy,
  ExternalLink,
  EyeOff,
  FileStack,
  Home,
  Pencil,
  Send,
  Settings2,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary, WikiRead } from "@/api/generated/initiativeAPI.schemas";
import { Tool, WikiPageKind } from "@/api/generated/initiativeAPI.schemas";
import {
  useDeleteWikiPage,
  useDuplicateWikiPage,
  useUpdateWiki,
  useUpdateWikiPage,
} from "@/hooks/useWikis";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { toolDetailRoute, wikiPageRoute } from "@/lib/tools";
import { Button } from "@/ui/button";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/ui/dropdown-menu";

interface WikiPageActionsProps {
  wiki: WikiRead;
  page: WikiPageSummary;
  canWrite: boolean;
  initiativeId: number;
  /** Takes a file back out of the wiki. Only a file row has one. */
  onRemoveFile?: () => void;
}

/**
 * What can be done to this page, as opposed to the wiki.
 *
 * It lives on the page's own row in the tree, beside the grip that moves it:
 * the tree is where a page is a thing you manage, and the page itself is where
 * it is a thing you read. Revealed on hover like every other row control, so a
 * wiki being read is a wiki with nothing in the way of the words.
 */
export const WikiPageActions = ({
  wiki,
  page,
  canWrite,
  initiativeId,
  onRemoveFile,
}: WikiPageActionsProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const gp = useCommunityPath();
  const navigate = useNavigate();
  const updateWiki = useUpdateWiki(wiki.id);
  const deletePage = useDeleteWikiPage(wiki.id);
  const updatePage = useUpdateWikiPage(wiki.id, page.id);
  const duplicatePage = useDuplicateWikiPage(wiki.id, {
    onSuccess: (copy) => {
      toast.success(t("common:subToolDuplicate.done"));
      void navigate({ to: gp(wikiPageRoute(initiativeId, wiki.id, copy.id)) });
    },
  });
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  if (!canWrite) {
    return null;
  }

  const isHome = wiki.home_page_id === page.id;
  const isTemplate = wiki.template_page_id === page.id;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="hidden h-6 w-0 shrink-0 overflow-hidden p-0 opacity-0 transition-all focus-visible:w-6 focus-visible:opacity-100 group-hover/page:w-6 group-hover/page:opacity-100 motion-reduce:transition-none md:flex"
            aria-label={t("page.actions")}
          >
            <Settings2 className="size-3.5" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64">
          {page.kind === WikiPageKind.file ? (
            <>
              <DropdownMenuItem asChild>
                <Link to={gp(toolDetailRoute(Tool.file, initiativeId, page.id))}>
                  <ExternalLink className="size-4" aria-hidden />
                  {t("files.openFile")}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive hover:text-destructive"
                onSelect={() => onRemoveFile?.()}
              >
                <Trash2 className="size-4" aria-hidden />
                {t("files.remove")}
              </DropdownMenuItem>
            </>
          ) : (
            <>
              {/* The other way into writing. The bar over the page offers it too;
              this is the one you reach for from the tree, without opening the
              page to read first. */}
              <DropdownMenuItem
                onSelect={() => {
                  void navigate({
                    to: gp(wikiPageRoute(initiativeId, wiki.id, page.id)),
                    search: { edit: true },
                  });
                }}
              >
                <Pencil className="size-4" aria-hidden />
                {t("viewMode.edit")}
              </DropdownMenuItem>

              <DropdownMenuSeparator />

              <DropdownMenuItem
                onSelect={() => {
                  updateWiki.mutate(
                    { home_page_id: page.id },
                    { onSuccess: () => toast.success(t("pages.homeSet")) }
                  );
                }}
                disabled={isHome}
              >
                {isHome ? (
                  <Check className="size-4" aria-hidden />
                ) : (
                  <Home className="size-4" aria-hidden />
                )}
                {isHome ? t("pages.isHome") : t("page.setHome")}
              </DropdownMenuItem>

              <DropdownMenuItem
                onSelect={() => {
                  updateWiki.mutate(
                    { template_page_id: page.id },
                    { onSuccess: () => toast.success(t("settings.saved")) }
                  );
                }}
                disabled={isTemplate}
              >
                {isTemplate ? (
                  <Check className="size-4" aria-hidden />
                ) : (
                  <FileStack className="size-4" aria-hidden />
                )}
                {isTemplate ? t("page.isTemplate") : t("page.useAsTemplate")}
              </DropdownMenuItem>

              {/* A draft is a page only the people who write here are shown. It is
              how you leave something half-finished in a wiki people read. */}
              <DropdownMenuItem
                onSelect={() => {
                  updatePage.mutate(
                    { is_draft: !page.is_draft },
                    {
                      onSuccess: () =>
                        toast.success(page.is_draft ? t("page.published") : t("page.drafted")),
                    }
                  );
                }}
              >
                {page.is_draft ? (
                  <Send className="size-4" aria-hidden />
                ) : (
                  <EyeOff className="size-4" aria-hidden />
                )}
                {page.is_draft ? t("page.publish") : t("page.markDraft")}
              </DropdownMenuItem>

              <DropdownMenuSeparator />

              <DropdownMenuItem
                disabled={duplicatePage.isPending}
                onSelect={() => duplicatePage.mutate(page.id)}
              >
                <Copy className="size-4" aria-hidden />
                {duplicatePage.isPending
                  ? t("common:subToolDuplicate.duplicating")
                  : t("common:subToolDuplicate.action")}
              </DropdownMenuItem>

              <DropdownMenuItem
                className="text-destructive hover:text-destructive"
                onSelect={() => setConfirmingDelete(true)}
              >
                <Trash2 className="size-4" aria-hidden />
                {t("page.delete")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("pages.deleteTitle")}
        description={t("pages.deleteDescription")}
        confirmLabel={t("page.delete")}
        onConfirm={() =>
          deletePage.mutate(page.id, {
            onSuccess: () => {
              toast.success(t("pages.deleted"));
              void navigate({
                to: gp(toolDetailRoute(Tool.wiki, initiativeId, wiki.id)),
              });
            },
          })
        }
      />
    </>
  );
};

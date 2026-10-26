import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { WikiPageSummary } from "@/api/generated/initiativeAPI.schemas";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useFilesList } from "@/hooks/useFiles";
import { useAddWikiFile } from "@/hooks/useWikis";
import { fileIcon } from "@/lib/fileIcon";
import { toast } from "@/lib/mascotToast";
import { cn } from "@/lib/utils";

interface AddWikiFileDialogProps {
  wikiId: number;
  initiativeId: number;
  /** What the wiki already holds, so it is not offered twice. */
  pages: WikiPageSummary[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Put a file that already exists into this wiki.
 *
 * Only files of the same initiative are offered: a wiki is an initiative's,
 * and reaching across one is a sharing decision rather than a filing one.
 *
 * Nothing is copied. The file keeps its address and its sharing, and this
 * only records that it belongs here too.
 *
 * Every kind of file is offered — an upload, a spreadsheet, a whiteboard, a
 * link — and each is read in the wiki the way its own kind is drawn.
 */
export const AddWikiFileDialog = ({
  wikiId,
  initiativeId,
  pages,
  open,
  onOpenChange,
}: AddWikiFileDialogProps) => {
  const { t } = useTranslation(["wikis", "common"]);
  const [query, setQuery] = useState("");
  const add = useAddWikiFile(wikiId);

  const filesQuery = useFilesList({ initiative_id: initiativeId, page_size: 0 }, { enabled: open });

  const already = useMemo(
    () => new Set(pages.filter((page) => page.kind === "file").map((page) => page.id)),
    [pages]
  );

  const needle = query.trim().toLowerCase();
  const candidates = (filesQuery.data?.items ?? [])
    .filter((file) => !already.has(file.id))
    .filter((file) => !needle || file.name.toLowerCase().includes(needle));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-5 py-4">
          <DialogTitle>{t("files.addFile")}</DialogTitle>
          <DialogDescription>{t("files.pick")}</DialogDescription>
        </DialogHeader>

        <div className="border-b px-5 py-3">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("filters.searchLabel")}
            aria-label={t("files.pick")}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {candidates.length === 0 ? (
            <p className="px-3 py-2 text-muted-foreground text-sm">{t("files.none")}</p>
          ) : (
            <ul className="space-y-0.5">
              {candidates.map((file) => {
                const { Icon, colorClass } = fileIcon({
                  file_type: file.file_type,
                  smart_link_url: file.smart_link_url,
                });
                return (
                  <li key={file.id}>
                    <Button
                      variant="ghost"
                      className="h-auto w-full justify-start gap-2 px-3 py-2 text-left"
                      disabled={add.isPending}
                      onClick={() =>
                        add.mutate(file.id, {
                          onSuccess: () => {
                            toast.success(t("files.added"));
                            onOpenChange(false);
                          },
                        })
                      }
                    >
                      <Icon className={cn("size-4 shrink-0", colorClass)} aria-hidden />
                      <span className="min-w-0 flex-1 truncate">{file.name}</span>
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
};

import { useState } from "react";
import { useTranslation } from "react-i18next";

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
import { fileIcon } from "@/lib/fileIcon";
import { cn } from "@/lib/utils";

interface FileChooserDialogProps {
  initiativeId: number;
  /** What the place already holds, so it is not offered twice. */
  exclude: ReadonlySet<number>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called with the file picked. The caller closes the dialog when it is in. */
  onPick: (fileId: number) => void;
  /** While a pick is being put in, the list waits. */
  pending: boolean;
  text: { title: string; description: string; none: string };
}

/**
 * Pick a file that already exists to put somewhere else too: a wiki, a
 * collection.
 *
 * Only files of the same initiative are offered: a wiki or a collection is an
 * initiative's, and reaching across one is a sharing decision rather than a
 * filing one.
 *
 * Nothing is copied. The file keeps its address and its sharing, and the
 * caller only records that it belongs there too.
 *
 * Every kind of file is offered — an upload, a spreadsheet, a whiteboard, a
 * link.
 */
export const FileChooserDialog = ({
  initiativeId,
  exclude,
  open,
  onOpenChange,
  onPick,
  pending,
  text,
}: FileChooserDialogProps) => {
  const { t } = useTranslation("files");
  const [query, setQuery] = useState("");

  const filesQuery = useFilesList({ initiative_id: initiativeId, page_size: 0 }, { enabled: open });

  const needle = query.trim().toLowerCase();
  const candidates = (filesQuery.data?.items ?? [])
    .filter((file) => !exclude.has(file.id))
    .filter((file) => !needle || file.name.toLowerCase().includes(needle));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col gap-0 p-0 sm:max-w-lg">
        <DialogHeader className="border-b px-5 py-4">
          <DialogTitle>{text.title}</DialogTitle>
          <DialogDescription>{text.description}</DialogDescription>
        </DialogHeader>

        <div className="border-b px-5 py-3">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("filters.searchFiles")}
            aria-label={text.description}
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {candidates.length === 0 ? (
            <p className="px-3 py-2 text-muted-foreground text-sm">{text.none}</p>
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
                      disabled={pending}
                      onClick={() => onPick(file.id)}
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

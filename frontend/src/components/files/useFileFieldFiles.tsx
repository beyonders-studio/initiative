import { FilePlus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { whereItLives } from "@/components/entities/EntityPicker";
import { CreateFileDialog } from "@/components/files/CreateFileDialog";
import { ReadOnlyFileBody } from "@/components/files/detail/ReadOnlyFileBody";
import type { FileFieldFiles } from "@/components/properties/FileFieldInput";
import type { FileFieldValue } from "@/components/properties/propertyHelpers";
import { useFile } from "@/hooks/useFiles";
import { useInitiative } from "@/hooks/useInitiatives";
import { usePickerSuggestionsNow } from "@/hooks/useSearch";
import { useCommunityPath } from "@/lib/communityUrl";
import { isStoredFileType } from "@/lib/fileTypes";
import { hitIcon } from "@/lib/searchResults";
import { entityRefRoute } from "@/lib/tools";
import { Button } from "@/ui/button";

/** A file this app draws itself, as its own page draws it, read-only. A
 *  body loads its content once, so it waits for this visit's own fetch. */
const FilePreview = ({ fileId }: { fileId: number }) => {
  const fileQuery = useFile(fileId);
  const file = fileQuery.data;
  return file && fileQuery.isFetchedAfterMount ? (
    <ReadOnlyFileBody file={file} className="max-h-96" />
  ) : null;
};

/** Files' own dialog, opened from a button, where the reader may make a file
 *  in the initiative. */
const NewFileButton = ({
  initiativeId,
  onMade,
}: {
  initiativeId: number;
  onMade: (file: FileFieldValue) => void;
}) => {
  const { t } = useTranslation("properties");
  const [open, setOpen] = useState(false);
  const initiative = useInitiative(initiativeId).data;
  if (!(initiative?.can.view.includes(Tool.file) && initiative.can.create.includes(Tool.file))) {
    return null;
  }
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        <FilePlus className="h-4 w-4" />
        {t("input.newFile")}
      </Button>
      <CreateFileDialog
        open={open}
        onOpenChange={setOpen}
        initiativeId={initiativeId}
        onSuccess={onMade}
      />
    </>
  );
};

/**
 * What a file field in an initiative picks from and draws with: the
 * initiative's files, found as every picker finds them, each linked to its
 * page; a file the app draws itself (a page, a whiteboard, a sheet, a smart
 * link) shown under its name, an uploaded one by its name alone; and Files'
 * own dialog to make one.
 */
export const useFileFieldFiles = (initiativeId: number | null): FileFieldFiles => {
  const suggestions = usePickerSuggestionsNow();
  const gp = useCommunityPath();
  return useMemo<FileFieldFiles>(() => {
    // A template's contents are not what somebody is reaching for here.
    const filters = {
      types: [SearchEntityType.file],
      initiative_id: initiativeId ?? undefined,
      is_template: false,
    };
    return {
      find: async (query) =>
        (await suggestions(query, filters)).map((item) => ({
          id: item.entity_id,
          label: item.title,
          icon: hitIcon(item),
          sublabel: whereItLives(item, initiativeId),
        })),
      href: (fileId) => gp(entityRefRoute(Tool.file, fileId)),
      preview: (file) =>
        file.file_type && !isStoredFileType(file.file_type) ? (
          <FilePreview fileId={file.id} />
        ) : null,
      newFile: (take) =>
        initiativeId === null ? null : <NewFileButton initiativeId={initiativeId} onMade={take} />,
    };
  }, [suggestions, gp, initiativeId]);
};

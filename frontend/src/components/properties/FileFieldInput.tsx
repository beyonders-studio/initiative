import { Link } from "@tanstack/react-router";
import { FilePlus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { EntityPicker } from "@/components/entities/EntityPicker";
import { CreateFileDialog } from "@/components/files/CreateFileDialog";
import { ReadOnlyFileBody } from "@/components/files/detail/ReadOnlyFileBody";
import { Button } from "@/components/ui/button";
import { useFile } from "@/hooks/useFiles";
import { useInitiative } from "@/hooks/useInitiatives";
import { useCommunityPath } from "@/lib/communityUrl";
import { isStoredFileType } from "@/lib/fileTypes";
import { entityRefRoute } from "@/lib/tools";

import { FileFieldName } from "./PropertyValueCell";
import type { FileFieldValue } from "./propertyHelpers";

interface FileFieldInputProps {
  /** The id of the file the field holds. */
  value: number | null;
  /** The field as the server last read it back. */
  shown: FileFieldValue | null;
  onChange: (value: number | null) => void;
  initiativeId: number | null;
  disabled?: boolean;
}

/** A file this app draws itself, as its own page draws it, read-only. */
const FilePreview = ({ fileId }: { fileId: number }) => {
  const file = useFile(fileId).data;
  return file ? <ReadOnlyFileBody file={file} className="max-h-96" /> : null;
};

/**
 * A file field: the one file it holds, a link to it, and a way to pick another
 * of the initiative's files or make one with Files' own dialog.
 *
 * A file the app draws itself (a page, a whiteboard, a sheet, a smart link) is
 * shown under its name as its own page shows it; an uploaded file is its name
 * alone.
 */
export const FileFieldInput = ({
  value,
  shown,
  onChange,
  initiativeId,
  disabled = false,
}: FileFieldInputProps) => {
  const { t } = useTranslation("properties");
  const gp = useCommunityPath();
  const [creating, setCreating] = useState(false);
  // What was picked here, drawn until the server reads it back.
  const [picked, setPicked] = useState<FileFieldValue | null>(null);
  const initiative = useInitiative(disabled ? null : initiativeId).data;
  const canCreate = Boolean(
    initiative?.can.view.includes(Tool.file) && initiative.can.create.includes(Tool.file)
  );

  const file =
    value === null ? null : ([picked, shown].find((each) => each?.id === value) ?? { id: value });
  const take = (next: FileFieldValue) => {
    setPicked(next);
    onChange(next.id);
  };

  return (
    <div className="flex min-w-0 flex-col gap-2">
      {file ? (
        file.name ? (
          <Link
            to={gp(entityRefRoute(Tool.file, file.id))}
            className="min-w-0 self-start text-sm hover:underline"
          >
            <FileFieldName file={file} />
          </Link>
        ) : (
          <FileFieldName file={file} />
        )
      ) : null}
      {file?.file_type && !isStoredFileType(file.file_type) ? (
        <FilePreview fileId={file.id} />
      ) : null}
      {disabled ? null : (
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <EntityPicker
              initiativeId={initiativeId}
              types={[SearchEntityType.file]}
              value={null}
              onChange={(next) => {
                if (next) take({ id: next.entity_id, name: next.title });
              }}
            />
          </div>
          {canCreate && initiativeId !== null ? (
            <Button type="button" variant="outline" size="sm" onClick={() => setCreating(true)}>
              <FilePlus className="h-4 w-4" />
              {t("input.newFile")}
            </Button>
          ) : null}
        </div>
      )}
      {canCreate && initiativeId !== null ? (
        <CreateFileDialog
          open={creating}
          onOpenChange={setCreating}
          initiativeId={initiativeId}
          onSuccess={(made) =>
            take({
              id: made.id,
              name: made.name,
              file_type: made.file_type,
              smart_link_url: made.smart_link_url,
            })
          }
        />
      ) : null}
    </div>
  );
};

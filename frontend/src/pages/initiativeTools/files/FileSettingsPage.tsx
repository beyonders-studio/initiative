import { useParams } from "@tanstack/react-router";

import { FileType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { useFileExportOptions } from "@/components/files/useFileExportOptions";
import { loadWhiteboardSceneFromContent } from "@/components/files/whiteboardSceneCache";
import { ToolSettingsLayout } from "@/components/tools/settings/ToolSettingsLayout";
import { useDeleteFile, useFile, useSetFileGrants, useUpdateFile } from "@/hooks/useFiles";

export const FileSettingsPage = () => {
  const { fileId } = useParams({ strict: false }) as { fileId?: string };
  const parsedId = fileId ? Number(fileId) : Number.NaN;
  const isValidId = Number.isFinite(parsedId);

  const fileQuery = useFile(isValidId ? parsedId : null);
  const file = fileQuery.data;

  const template = useUpdateFile(parsedId);
  const setGrants = useSetFileGrants(parsedId);
  const remove = useDeleteFile();

  // A whiteboard's pictures are drawn from the scene the server holds; the
  // editor has saved it by the time anybody is here.
  const exportOptions = useFileExportOptions(
    file?.file_type ?? FileType.lexical,
    file?.name ?? "",
    file?.file_type === FileType.excalidraw
      ? loadWhiteboardSceneFromContent(file.content)
      : undefined
  );

  return (
    <ToolSettingsLayout
      tool={Tool.file}
      // A file's name is edited in the editor rather than here, and it
      // carries no description field.
      entity={file}
      isLoading={isValidId && fileQuery.isLoading}
      isError={!isValidId || fileQuery.isError}
      template={template}
      setGrants={setGrants}
      remove={remove}
      exportOptions={exportOptions}
    />
  );
};

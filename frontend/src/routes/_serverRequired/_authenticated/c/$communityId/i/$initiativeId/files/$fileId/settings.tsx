import { createFileRoute } from "@tanstack/react-router";

import { FileType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { loadWhiteboardSceneFromContent } from "@/components/tools/files/whiteboardSceneCache";
import { useFile } from "@/hooks/useFiles";
import { useRouteId } from "@/hooks/useRouteId";
import { useFileExportOptions } from "@/pages/community/tools/files/useFileExportOptions";
import { SettingsLayout } from "@/pages/community/tools/settings/SettingsLayout";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/$fileId/settings"
)({
  component: FileSettings,
});

function FileSettings() {
  const file = useFile(useRouteId("fileId")).data;
  // A whiteboard's pictures are drawn from the scene the server holds; the
  // editor has saved it by the time anybody is here.
  const exportOptions = useFileExportOptions(
    file?.file_type ?? FileType.lexical,
    file?.name ?? "",
    file?.file_type === FileType.excalidraw
      ? loadWhiteboardSceneFromContent(file.content)
      : undefined
  );

  // A file's name is edited in the editor rather than here, and it carries no
  // description.
  return <SettingsLayout tool={Tool.file} detailsForm={false} exportOptions={exportOptions} />;
}

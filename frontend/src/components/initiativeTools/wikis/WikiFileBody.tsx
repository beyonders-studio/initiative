import { Loader2 } from "lucide-react";
import { Suspense, useMemo } from "react";

import type { FileRead } from "@/api/generated/initiativeAPI.schemas";
import { fileBody } from "@/components/files/detail/fileBodies";
import { useCollaboration } from "@/hooks/useCollaboration";

const ignore = () => {};

/** Whether a file reads best across the wiki's wide column: everything
 * that is not written prose. */
export const isWideFile = (file: FileRead | undefined) =>
  file !== undefined && !fileBody(file.file_type).prose;

/**
 * A file in a wiki, drawn by the body its own page draws it with — a file
 * in its viewer, a whiteboard on its canvas, a spreadsheet in its grid — and
 * never edited here. Writing happens at the file's own address, so the
 * body joins no room and its edits go nowhere.
 */
export const WikiFileBody = ({ file }: { file: FileRead }) => {
  // What the file page holds for a body that joins no room.
  const collaboration = useCollaboration({ socketPath: null, enabled: false });
  const { Body, saved, prose } = fileBody(file.file_type);
  const content = useMemo(() => saved(file), [saved, file]);

  return (
    <Suspense
      fallback={
        <div className="flex h-96 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <Body
        key={file.id}
        file={file}
        saved={content}
        canEdit={false}
        collaboration={collaboration}
        live={false}
        settled
        title={file.name}
        // Prose runs on in the wiki's own column rather than in a card.
        className={
          prose ? "max-h-none rounded-none border-0 bg-transparent shadow-none" : undefined
        }
        compact
        onChange={ignore}
      />
    </Suspense>
  );
};

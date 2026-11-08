import { Loader2 } from "lucide-react";
import { Suspense, useMemo } from "react";

import type { FileRead } from "@/api/generated/initiativeAPI.schemas";
import { useCollaboration } from "@/hooks/useCollaboration";

import { fileBody } from "./fileBodies";

const ignore = () => {};

/** Whether a file reads best across a wide column: everything that is not
 * written prose. */
export const isWideFile = (file: FileRead | undefined) =>
  file !== undefined && !fileBody(file.file_type).prose;

/**
 * A file shown where it does not live (a wiki, a file field), drawn by the
 * body its own page draws it with — a file in its viewer, a whiteboard on its
 * canvas, a spreadsheet in its grid — and never edited there. Writing happens
 * at the file's own address, so the body joins no room and its edits go
 * nowhere.
 */
export const ReadOnlyFileBody = ({ file, className }: { file: FileRead; className?: string }) => {
  // What the file page holds for a body that joins no room.
  const collaboration = useCollaboration({ socketPath: null, enabled: false });
  const { Body, saved } = fileBody(file.file_type);
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
        className={className}
        compact
        onChange={ignore}
      />
    </Suspense>
  );
};

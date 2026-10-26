import { useNavigate } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { ExternalLink, Loader2 } from "lucide-react";
import { type ComponentType, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { importSpreadsheetFile } from "@/api/generated/files/files";
import type { FileRead, FileType } from "@/api/generated/initiativeAPI.schemas";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import type { SmartLinkContent } from "@/components/files/SmartLinkFileViewer";
import type { SpreadsheetContent } from "@/components/files/SpreadsheetFileEditor";
import type { WhiteboardScene } from "@/components/files/WhiteboardFileEditor";
import {
  loadWhiteboardScene,
  stampWhiteboardSceneCache,
  type WhiteboardSceneLoad,
} from "@/components/files/whiteboardSceneCache";
import { CreateReferencedThingDialog } from "@/components/references/CreateReferencedThingDialog";
import { Button } from "@/components/ui/button";
import type { UseCollaborationResult } from "@/hooks/useCollaboration";
import { useCommunities, useSelfInCommunity } from "@/hooks/useCommunities";
import { useCommunityPath } from "@/lib/communityUrl";
import { normalizeEditorState } from "@/lib/editorState";
import { type EditorFileType, isStoredFileType } from "@/lib/fileTypes";
import { supportsEntityMentions } from "@/lib/mentions";
import { referenceRef } from "@/lib/smartChips";
import type { SpreadsheetSheetContent } from "@/lib/spreadsheet/content";
import { toolDetailRoute } from "@/lib/tools";
import { getUserDisplayName } from "@/lib/userDisplay";
import { cn } from "@/lib/utils";

const Editor = lazy(() =>
  import("@/components/ui/editor/editor").then((m) => ({ default: m.Editor }))
);
const UploadedFileViewer = lazy(() =>
  import("@/components/files/UploadedFileViewer").then((m) => ({
    default: m.UploadedFileViewer,
  }))
);
const SpreadsheetFileEditor = lazy(() =>
  import("@/components/files/SpreadsheetFileEditor").then((m) => ({
    default: m.SpreadsheetFileEditor,
  }))
);
const WhiteboardFileEditor = lazy(() =>
  import("@/components/files/WhiteboardFileEditor").then((m) => ({
    default: m.WhiteboardFileEditor,
  }))
);
const SmartLinkFileViewer = lazy(() =>
  import("@/components/files/SmartLinkFileViewer").then((m) => ({
    default: m.SmartLinkFileViewer,
  }))
);

/** What the file page hands every body. The page keys it by file. */
export interface FileBodyProps {
  file: FileRead;
  /** The saved body, in the shape this type reports edits in. */
  saved: unknown;
  canEdit: boolean;
  collaboration: UseCollaborationResult;
  /** Live collaboration is on and its room is ready. */
  live: boolean;
  /** The fetch behind `file` has come back since the page opened. */
  settled: boolean;
  title: string;
  className?: string;
  /** Prose only: the container already supplies the horizontal gutter. */
  compact?: boolean;
  /** Reports what the body now holds — the edit the page saves. */
  onChange: (content: unknown) => void;
}

/** One file type's body, and what the page around it does for that type.
 *  A capability left out is one the type does not have. */
export interface FileTypeBody {
  Body: ComponentType<FileBodyProps>;
  /** The saved body, as the dirty check and a save carrying no edit read it. */
  saved: (file: FileRead) => unknown;
  /** Controls of its own in the editor's toolbar row, before fullscreen. */
  Actions?: ComponentType<{ file: FileRead }>;
  /** Sits in the editor frame: toolbar and fullscreen. */
  framed?: boolean;
  /** Edited on this page, so the frame carries the save bar. */
  editable?: boolean;
  /**
   * Joins the file's live room, which renders the content column from its
   * Yjs state. This paces the rest of a save while it is live: the name and
   * the featured image.
   */
  roomSyncMs?: number;
  /** Prose: headings to navigate and an AI summary. */
  prose?: boolean;
}

/** The signed-in user as presence shows them. Memoized so awareness effects
 *  key on the identity rather than an object made every render. */
const usePresenceUser = () => {
  const user = useSelfInCommunity();
  return useMemo(
    () => (user ? { id: user.id, name: getUserDisplayName(user, "Anonymous") } : null),
    [user]
  );
};

/**
 * The room's Yjs doc and awareness, for a body that binds its own editor to
 * them. Asking the factory reuses the provider or opens it, the way Lexical's
 * CollaborationPlugin does for prose; useCollaboration owns its lifecycle, so
 * there is nothing to clean up here.
 */
const useRoomProvider = ({ providerFactory }: UseCollaborationResult, live: boolean) => {
  type Provider = ReturnType<NonNullable<typeof providerFactory>>;
  const [provider, setProvider] = useState<Provider | null>(null);
  useEffect(() => {
    setProvider(live && providerFactory ? providerFactory("main", new Map()) : null);
  }, [live, providerFactory]);
  return live ? provider : null;
};

const NativeBody = ({
  file,
  saved,
  canEdit,
  collaboration,
  live,
  className,
  compact,
  onChange,
}: FileBodyProps) => {
  const navigate = useNavigate();
  const gp = useCommunityPath();
  // `[[ ]]` found nothing and offered to make it. The dialog owns which kind
  // and whether this writer may; the reference it answers with goes straight
  // into the sentence, so making something never costs the writer their place.
  const [creating, setCreating] = useState<{
    name: string;
    onCreated: (entityType: SearchEntityType, entityId: number, name: string) => void;
  } | null>(null);

  const handleWikilinkNavigate = useCallback(
    (targetFileId: number) => {
      void navigate({
        to: gp(toolDetailRoute(Tool.file, file.initiative_id, targetFileId)),
      });
    },
    [navigate, gp, file.initiative_id]
  );
  const handleCreateReferencedThing = useCallback(
    (name: string, onCreated: NonNullable<typeof creating>["onCreated"]) =>
      setCreating({ name, onCreated }),
    []
  );

  return (
    <>
      <Editor
        editorSerializedState={saved as SerializedEditorState}
        onSerializedChange={onChange}
        readOnly={!canEdit}
        showToolbar={canEdit}
        className={cn("max-h-[80vh] bg-card", className)}
        collaborative={live}
        providerFactory={collaboration.providerFactory}
        // Always track changes so the page's copy stays updated for periodic saves
        trackChanges={true}
        hasSynced={collaboration.hasSynced}
        initiativeId={file.initiative_id}
        subject={referenceRef(SearchEntityType.file, file.id)}
        supportsEntityMentions={supportsEntityMentions(file.file_type)}
        onWikilinkNavigate={handleWikilinkNavigate}
        onCreateReferencedThing={handleCreateReferencedThing}
        compact={compact}
      />
      {creating && (
        <CreateReferencedThingDialog
          name={creating.name}
          initiativeId={file.initiative_id}
          onCreated={(made) => {
            creating.onCreated(made.entityType, made.entityId, made.name);
            setCreating(null);
          }}
          onClose={() => setCreating(null)}
        />
      )}
    </>
  );
};

const WhiteboardBody = ({
  file,
  canEdit,
  collaboration,
  live,
  settled,
  className,
  onChange,
}: FileBodyProps) => {
  const room = useRoomProvider(collaboration, live);
  const currentUser = usePresenceUser();
  // The editor reads its scene once, at mount, so it waits for this. The
  // write-ahead cache wins only while it is strictly newer than
  // file.updated_at, and a cached snapshot's timestamp makes any local
  // cache look newer than it is — so the scene is loaded once the fetch has
  // settled. (An errored fetch settles too, so offline still falls back to the
  // cached file.)
  const [load, setLoad] = useState<WhiteboardSceneLoad | null>(null);
  useEffect(() => {
    if (load || !settled) return;
    const next = loadWhiteboardScene(
      file.id,
      file.updated_at,
      file.content as Partial<WhiteboardScene> | null
    );
    setLoad(next);
    // A cached scene is edits the server has not seen: unsaved work.
    if (next.fromCache) onChange(next.scene);
  }, [load, settled, file, onChange]);

  // Only genuine local edits stamp the write-ahead cache: remote-applied
  // updates flow through here too (the periodic REST sync needs them), and
  // stamping on those would leave every watching session holding a
  // fresh-looking cache that a later revisit would prefer over the live room.
  const handleChange = useCallback(
    (scene: WhiteboardScene, opts?: { isLocal: boolean }) => {
      onChange(scene);
      if (opts?.isLocal === false) return;
      stampWhiteboardSceneCache(file.id, scene);
    },
    [onChange, file.id]
  );

  if (!load) {
    return (
      <div className="flex h-96 items-center justify-center rounded-xl border">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }
  return (
    <WhiteboardFileEditor
      initialScene={load.scene}
      initialSceneFromCache={load.fromCache}
      onSerializedChange={handleChange}
      readOnly={!canEdit}
      yDoc={room?.doc ?? null}
      isSynced={collaboration.isSynced}
      // The server roster includes ourselves — only *other* users make the
      // room's Yjs state authoritative over a local write-ahead cache.
      hasOtherCollaborators={collaboration.collaborators.some((c) => c.user_id !== currentUser?.id)}
      collaboratorsReady={collaboration.collaboratorsReady}
      awareness={room?.awareness ?? null}
      currentUser={currentUser}
      className={className}
    />
  );
};

const SpreadsheetBody = ({
  file,
  saved,
  canEdit,
  collaboration,
  live,
  title,
  className,
  onChange,
}: FileBodyProps) => {
  const room = useRoomProvider(collaboration, live);
  const currentUser = usePresenceUser();
  const { activeCommunityId } = useCommunities();
  // Reading a file is the host's job — it knows which file and community the
  // editor is showing. What comes back is sheets; the editor adds them to its
  // live workbook itself, in one transaction.
  const importSheets = useCallback(
    async (upload: File) => {
      if (!activeCommunityId) return [];
      const result = await importSpreadsheetFile(activeCommunityId, file.id, { file: upload });
      return result.sheets as unknown as SpreadsheetSheetContent[];
    },
    [activeCommunityId, file.id]
  );

  return (
    <SpreadsheetFileEditor
      initialContent={saved as SpreadsheetContent}
      onContentChange={onChange}
      fileTitle={title || file.name}
      readOnly={!canEdit}
      yDoc={room?.doc ?? null}
      isSynced={collaboration.isSynced}
      hasSynced={collaboration.hasSynced}
      awareness={room?.awareness ?? null}
      currentUser={currentUser}
      onImportFile={canEdit ? importSheets : undefined}
      className={cn("max-h-[70vh]", className)}
    />
  );
};

const SmartLinkBody = ({ file, className }: FileBodyProps) => (
  <SmartLinkFileViewer
    content={file.content as unknown as SmartLinkContent | null}
    className={className}
  />
);

const SmartLinkActions = ({ file }: { file: FileRead }) => {
  const { t } = useTranslation("files");
  const url = (file.content as { url?: unknown } | null)?.url;
  if (typeof url !== "string") return null;
  return (
    <Button asChild type="button" variant="ghost" size="sm" className="ml-auto">
      <a href={url} target="_blank" rel="noopener noreferrer">
        <ExternalLink className="h-4 w-4" />
        {t("smartLink.openInNewTab")}
      </a>
    </Button>
  );
};

const FileBody = ({ file, canEdit }: FileBodyProps) =>
  file.file_url ? (
    <UploadedFileViewer
      fileId={file.id}
      communityId={file.community_id}
      fileUrl={file.file_url}
      contentType={file.file_content_type}
      originalFilename={file.original_filename}
      fileSize={file.file_size}
      canEdit={canEdit}
      canDeleteVersions={file.can.delete}
    />
  ) : null;

// Spreadsheet and whiteboard content is not a Lexical tree: passed through
// the normalizer it would come back empty, read as an edit against the real
// content, and fire an autosave on every open.
const rawContent = (file: FileRead): unknown => file.content ?? {};
const lexicalContent = (file: FileRead): unknown =>
  normalizeEditorState(file.content as unknown as SerializedEditorState | null | undefined);

/** The body of each type the editor keeps. A new one is one entry here. */
const EDITOR_BODIES: Record<EditorFileType, FileTypeBody> = {
  lexical: {
    Body: NativeBody,
    saved: lexicalContent,
    framed: true,
    editable: true,
    roomSyncMs: 10_000,
    prose: true,
  },
  excalidraw: {
    Body: WhiteboardBody,
    saved: rawContent,
    framed: true,
    editable: true,
    roomSyncMs: 2000,
  },
  sheet: {
    Body: SpreadsheetBody,
    saved: rawContent,
    framed: true,
    editable: true,
    roomSyncMs: 2000,
  },
  // Nothing on this page edits the link: a save echoes the content back so a
  // rename or a featured-image change does not rewrite the URL.
  url: {
    Body: SmartLinkBody,
    saved: (file) => file.content,
    Actions: SmartLinkActions,
    framed: true,
  },
};

/** Every stored type's body: the uploaded file's viewer. */
const STORED_BODY: FileTypeBody = { Body: FileBody, saved: lexicalContent };

export const fileBody = (type: FileType): FileTypeBody =>
  isStoredFileType(type) ? STORED_BODY : EDITOR_BODIES[type];

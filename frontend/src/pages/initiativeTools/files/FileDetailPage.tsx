import { useParams } from "@tanstack/react-router";
import type { SerializedEditorState } from "lexical";
import { ListTree, Loader2, Maximize2, Minimize2, PanelRight, Save } from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { API_BASE_URL } from "@/api/client";
import { generateSummary, notifyMentions } from "@/api/generated/files/files";
import { FileKind, Tool } from "@/api/generated/initiativeAPI.schemas";
import { type AISummary, SummarySheet, useSummarySheet } from "@/components/ai/SummarySheet";
import { ToolCommentsPanel } from "@/components/comments/ToolCommentsPanel";
import { ToolRelationsPanel } from "@/components/entities/ToolRelationsPanel";
import { FileCollections } from "@/components/files/collections/FileCollections";
import { fileBody } from "@/components/files/detail/fileBodies";
import { FileFeaturedImage } from "@/components/files/FileFeaturedImage";
import { clearWhiteboardSceneCache } from "@/components/files/whiteboardSceneCache";
import { FileDetailSkeleton } from "@/components/skeletons/PageSkeletons";
import { ToolAccessStatus } from "@/components/ToolAccessStatus";
import { ToolChest, ToolChestSegment } from "@/components/tools/ToolChest";
import { ToolPageHeader } from "@/components/tools/ToolPageHeader";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { CollaborationStatusBadge } from "@/components/ui/editor/CollaborationStatusBadge";
import { FeaturedImageProvider } from "@/components/ui/editor/context/featured-image-context";
import {
  DocumentOutlinePanel,
  DocumentOutlineScope,
  useDocumentOutline,
} from "@/components/ui/editor/DocumentOutline";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAIEnabled } from "@/hooks/useAIEnabled";
import { useAuth } from "@/hooks/useAuth";
import { useCanonicalInitiativeId } from "@/hooks/useCanonicalInitiativeId";
import { useCollaboration } from "@/hooks/useCollaboration";
import { useCommunities } from "@/hooks/useCommunities";
import { useFile, useSetFileCache, useUpdateFile } from "@/hooks/useFiles";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useReadOnOpen } from "@/hooks/useNotifications";
import { useRecordOpen } from "@/hooks/usePersonalItems";
import { useRelativeTime } from "@/hooks/useRelativeTime";
import { useServerForm } from "@/hooks/useServerForm";
import { uploadAttachment } from "@/lib/attachmentUtils";
import { useCommunityPath } from "@/lib/communityUrl";
import { toast } from "@/lib/mascotToast";
import { findNewMentions } from "@/lib/mentionUtils";
import { toolListRoute, toolRouteSegment, toolSettingsRoute } from "@/lib/tools";
import { cn } from "@/lib/utils";
import { CollaborationError } from "@/lib/yjs/CollaborationProvider";

export const FileDetailPage = () => {
  const { t } = useTranslation(["files", "properties", "common", "editor"]);
  const { communityId: communityIdParam, fileId } = useParams({ strict: false }) as {
    communityId: string;
    fileId: string;
  };
  const parsedId = Number(fileId);
  const setFileCache = useSetFileCache();
  const { user, token } = useAuth();
  const { activeCommunityId } = useCommunities();
  const communityId = Number(communityIdParam);
  const gp = useCommunityPath();
  const sidePanel = useSummarySheet("file-side-panel-open");
  const outline = useDocumentOutline();
  const { isEnabled: isAIEnabled } = useAIEnabled();
  const [aiSummary, setAiSummary] = useState<AISummary | null>(null);
  const [featuredImageUrl, setFeaturedImageUrl] = useState<string | null>(null);
  const [isUploadingFeaturedImage, setIsUploadingFeaturedImage] = useState(false);
  // What the body last reported, and for which file: the page's copy of
  // the edit, read by the dirty check and the saves. Nothing until the body
  // reports — the editor reads the saved body once, at mount, and this copy is
  // never replaced by a later answer, so the two cannot come to disagree.
  const [edited, setEdited] = useState<{ fileId: number; content: unknown } | null>(null);
  const [autosaveEnabled, setAutosaveEnabled] = useState(true);
  const [collaborationEnabled, setCollaborationEnabled] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const isAutosaveRef = useRef(false);

  // Network status for offline detection
  const { isOnline } = useNetworkStatus();

  const fileQuery = useFile(Number.isFinite(parsedId) ? parsedId : null);
  const file = fileQuery.data;
  const bodyKind = file ? fileBody(file.file_type) : null;
  // Whether this file's room is in play: a body that joins none has no
  // work in a Yjs doc to hand over, and no connection to show.
  const joinsRoom = collaborationEnabled && (!bodyKind || bodyKind.roomSyncMs !== undefined);

  // Collaboration hook - only enable when we have a valid file ID and a
  // body that joins a room. The WebSocket opens lazily when something calls
  // `providerFactory`: Lexical's CollaborationPlugin (inside <Editor>) or a
  // body binding its own editor to the room's Y.Doc. Leaving `enabled` on
  // while the type is still loading matters: gating on the fetched type would
  // delay Lexical's CollaborationPlugin initial mount past the first render
  // where `<Editor>` appears, which regresses the collab bootstrap and leaves
  // Lexical stuck on "Syncing document…".
  const collaboration = useCollaboration({
    socketPath: Number.isFinite(parsedId)
      ? `${toolRouteSegment(Tool.file)}/${parsedId}/collaborate`
      : null,
    enabled: joinsRoom && Number.isFinite(parsedId),
    onError: (error) => {
      toast.error(t("detail.collaborationFailed"), {
        description: error.message || t("detail.collaborationFailedDescription"),
      });
      // Only a refusal ends the session. A lost connection leaves the provider
      // trying, and turning collaboration off here would tear down the socket
      // that is going to carry this tab's work back — anything typed during an
      // outage lives in the local doc until the sync handshake hands it over.
      if (!(error instanceof CollaborationError) || !error.recoverable) {
        setCollaborationEnabled(false);
      }
    },
  });

  // The name follows the file until somebody starts renaming it: a
  // refetch — a comment on this file, a window coming back to the front —
  // must not take a half-typed name away, and a rename by somebody else must
  // still arrive while nobody here is typing one.
  const titleField = useServerForm(file, (loaded) => ({ title: loaded?.name ?? "" }), file?.id);
  const title = titleField.values.title;
  const setTitle = (next: string) => titleField.set({ title: next });
  // Whether the name field is being typed in right now. Autosave waits it out
  // so the Save button beside the field stays put for as long as it is wanted.
  const [titleHasFocus, setTitleHasFocus] = useState(false);
  // The path supplies the initiative while this loads, but the entity is the
  // authority once it arrives — a URL naming a different one is corrected
  // rather than left to build links into an initiative it isn't in.
  const initiativeId = useCanonicalInitiativeId(file?.initiative_id);
  const relativeUpdatedAt = useRelativeTime(file?.updated_at);

  // Track recently viewed files so the layout header tabs bar can surface
  // them. Mirrors the pattern in ProjectDetailPage.
  const viewedFileId = fileQuery.data?.id;
  useReadOnOpen(Tool.file, viewedFileId);
  useRecordOpen(Tool.file, viewedFileId);

  // Which file the featured image below was filled in from. Filled in
  // once per file, for the reason the body's copy is: a later answer
  // replacing it would leave the page believing it matches the server.
  const seededFileRef = useRef<number | null>(null);

  useEffect(() => {
    seededFileRef.current = null;
  }, [parsedId]);

  // Lock body scroll while the editor is in fullscreen so wheel events
  // over the overlay don't bleed through to the page beneath.
  useEffect(() => {
    if (!isFullscreen) return;
    const body = window.document.body;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    return () => {
      body.style.overflow = previousOverflow;
    };
  }, [isFullscreen]);

  useEffect(() => {
    if (!file) {
      return;
    }
    // Tags are written the moment they are picked, so they go on following the
    // server whether or not the rest has been filled in.
    if (seededFileRef.current === file.id) {
      return;
    }
    // Opening a file already in the React Query cache renders it from that
    // snapshot before this mount's fetch has been anywhere. It predates
    // whatever else has happened since, so it is filled in but not committed:
    // every answer up to and including this mount's own is taken, and only
    // that one closes the door.
    if (fileQuery.isFetchedAfterMount) {
      seededFileRef.current = file.id;
    }
    setFeaturedImageUrl(file.featured_image_url ?? null);
  }, [file, fileQuery.isFetchedAfterMount]);

  const saved = useMemo(() => (file ? fileBody(file.file_type).saved(file) : undefined), [file]);
  const editedBody = edited?.fileId === parsedId ? edited.content : undefined;
  const savedJson = useMemo(() => JSON.stringify(saved), [saved]);
  const editedJson = useMemo(() => JSON.stringify(editedBody), [editedBody]);
  // What a save carries for the body: the edit, or the saved body echoed back.
  const contentForSave = (editedBody ?? saved) as Record<string, unknown>;
  // Server-computed: already capped at "read" when the community's content is
  // frozen (read_only lifecycle status) or access is via a read-level grant.
  // Write or owner may also moderate the file's comments.
  const canEditFile = Boolean(user) && Boolean(file?.can.edit);
  // Split by what a save would carry: a rename and the rest of the file
  // are committed on different terms — see the autosave effect.
  const nameIsDirty = Boolean(file) && title?.trim() !== file?.name?.trim();
  const bodyIsDirty =
    (editedBody !== undefined && editedJson !== savedJson) ||
    (file?.featured_image_url ?? null) !== featuredImageUrl;
  const isDirty = canEditFile && (nameIsDirty || bodyIsDirty);

  const titleIsDirty = canEditFile && nameIsDirty;

  const updateFileCommentCount = (delta: number) => {
    setFileCache(parsedId, (previous) => {
      if (!previous) return previous;
      const nextCount = Math.max(0, (previous.comment_count ?? 0) + delta);
      return { ...previous, comment_count: nextCount };
    });
  };

  // Only the template flag, from the tool chest's status: kept apart from the
  // save above, which settles the editor's draft when it lands.
  const setTemplate = useUpdateFile(parsedId);
  const saveFile = useUpdateFile(parsedId, {
    onSuccess: (_updated, sent) => {
      // Only if the field still holds the name this save carried: an autosave
      // that started before the last keystroke must not mark it saved. A save
      // that carried no name at all (one made while the field was being typed
      // in) settles nothing.
      if (typeof sent.name === "string") {
        titleField.settle({ title: sent.name });
      }
      if (!isAutosaveRef.current) {
        toast.success(t("detail.saved"));
      }
      // Clear the write-ahead cache — the DB is now up-to-date.
      clearWhiteboardSceneCache(parsedId);
      // Fire-and-forget: notify users who were newly mentioned
      const newMentionIds = findNewMentions(
        saved as SerializedEditorState | undefined,
        editedBody as SerializedEditorState | undefined
      );
      if (newMentionIds.length > 0) {
        notifyMentions(communityId, parsedId, {
          mentioned_user_ids: newMentionIds,
        }).catch((err) => console.error("Failed to notify mentions:", err));
      }
    },
    onSettled: () => {
      isAutosaveRef.current = false;
    },
  });

  // Updates the ref with the state, so the room's handover never reads an
  // older edit than the one on screen.
  const handleBodyChange = useCallback(
    (content: unknown) => {
      setEdited({ fileId: parsedId, content });
    },
    [parsedId]
  );

  // Autosave with debounce
  useEffect(() => {
    if (!autosaveEnabled || !canEditFile || saveFile.isPending) {
      return;
    }
    // Skip all REST saves while offline — edits remain in local state and will
    // be flushed when the network returns (see reconnect effect below).
    if (!isOnline) {
      return;
    }
    // A rename in progress belongs to the person typing it: taking it retires
    // the Save button beside the field mid-reach. The name waits for the field
    // to be let go — leaving the page still flushes it (see the unmount/unload
    // flush below) — while the body carries on saving on its own schedule.
    const savesName = nameIsDirty && !titleHasFocus;
    // Nothing this pass would write. The collaborating branch below checks
    // this too: the room owns the content column while it is live, but an open
    // file nobody is editing has no rendering to report and no name to send.
    if (!savesName && !bodyIsDirty) {
      return;
    }
    // When collaborating, the room is the writer of this file's content
    // column: it renders the content from its Yjs state, and saves the two
    // together. The PATCH carries the rest, at the body's own pace.
    if (collaboration.isCollaborating) {
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveFile.mutate({
          ...(savesName ? { name: title?.trim() } : null),
          featured_image_url: featuredImageUrl,
        });
      }, bodyKind?.roomSyncMs ?? 10_000);
      return () => clearTimeout(timer);
    } else {
      const timer = setTimeout(() => {
        isAutosaveRef.current = true;
        saveFile.mutate({
          ...(savesName ? { name: title?.trim() } : null),
          content: contentForSave,
          featured_image_url: featuredImageUrl,
        });
      }, 2000);
      return () => clearTimeout(timer);
    }
  }, [
    autosaveEnabled,
    nameIsDirty,
    bodyIsDirty,
    canEditFile,
    saveFile,
    parsedId,
    title,
    contentForSave,
    featuredImageUrl,
    collaboration.isCollaborating,
    isOnline,
    bodyKind,
    titleHasFocus,
  ]);

  // When connectivity returns after being offline, flush any pending dirty
  // changes immediately. This handles the case where the user stopped typing
  // while offline (so the 2s debounce already cleared) and is necessary
  // because the autosave effect only fires on new edits.
  const prevOnlineRef = useRef(isOnline);
  useEffect(() => {
    const wasOffline = !prevOnlineRef.current;
    prevOnlineRef.current = isOnline;
    if (!wasOffline || !isOnline) return;
    if (!canEditFile || saveFile.isPending) return;
    if (joinsRoom) {
      // The work done while offline is in this tab's Yjs doc, and the sync
      // handshake is what carries it over — merged with whatever the rest of
      // the room did meanwhile, rather than written over it. The REST path
      // carries a rendering rather than the work itself, and the server keeps
      // the content column with the room for that reason.
      collaboration.resume();
      return;
    }
    if (!isDirty) return;
    // Do NOT set isAutosaveRef here — we want the success toast to fire so
    // users who edited while offline get explicit confirmation their work
    // was persisted after reconnecting.
    saveFile.mutate({
      name: title?.trim(),
      content: contentForSave,
      featured_image_url: featuredImageUrl,
    });
  }, [
    isOnline,
    canEditFile,
    isDirty,
    saveFile,
    parsedId,
    joinsRoom,
    collaboration,
    title,
    contentForSave,
    featuredImageUrl,
  ]);

  // ── Unmount / unload flush ──────────────────────────────────────────
  // Mirrors the current save payload into a ref so the unmount flush has
  // the most recent data even if the autosave debounce was cancelled
  // mid-flight (e.g. user draws a shape and refreshes within 2 seconds).
  // Without this, the autosave timer is cleared on unmount and the edit
  // is lost. Especially important for whiteboards where a single drawing
  // action comfortably fits inside the debounce window.
  const pendingSavePayloadRef = useRef<{
    fileId: number;
    data: {
      name?: string;
      content: Record<string, unknown>;
      featured_image_url: string | null;
    };
  } | null>(null);
  useEffect(() => {
    if (!canEditFile || !isDirty) {
      pendingSavePayloadRef.current = null;
      return;
    }
    pendingSavePayloadRef.current = {
      fileId: parsedId,
      data: {
        name: title?.trim(),
        content: contentForSave,
        featured_image_url: featuredImageUrl,
      },
    };
  }, [canEditFile, isDirty, parsedId, title, contentForSave, featuredImageUrl]);

  // Hold token and activeCommunityId in refs so the flush closure always sees
  // the latest values without the effect needing to re-run on JWT rotation.
  // Without this, a token refresh would trigger the cleanup → flush() →
  // null the pending ref, and the ref-populating effect wouldn't re-run
  // (its deps didn't change), silently dropping the next pending save.
  const tokenRef = useRef(token);
  const activeCommunityIdRef = useRef(activeCommunityId);
  useEffect(() => {
    tokenRef.current = token;
  }, [token]);
  useEffect(() => {
    activeCommunityIdRef.current = activeCommunityId;
  }, [activeCommunityId]);

  useEffect(() => {
    const flush = () => {
      const pending = pendingSavePayloadRef.current;
      if (!pending || !tokenRef.current || !activeCommunityIdRef.current) return;
      const isAbsolute = API_BASE_URL.startsWith("http://") || API_BASE_URL.startsWith("https://");
      const baseUrl = isAbsolute ? API_BASE_URL : `${window.location.origin}${API_BASE_URL}`;
      // The community rides in the path (`/c/{communityId}/`) — community context is per-tab
      // from the URL; the page required entering this file's community.
      const url = `${baseUrl}/c/${activeCommunityIdRef.current}/${toolRouteSegment(Tool.file)}/${pending.fileId}`;
      fetch(url, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${tokenRef.current}`,
        },
        body: JSON.stringify(pending.data),
        keepalive: true,
      }).catch(() => {});
      pendingSavePayloadRef.current = null;
    };

    const handleBeforeUnload = () => flush();
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      flush();
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, []);

  // Persistent offline toast with mode-aware copy
  useEffect(() => {
    const TOAST_ID = "editor-offline";
    if (isOnline) {
      toast.dismiss(TOAST_ID);
      return;
    }
    const message = collaboration.isCollaborating
      ? t("detail.offline.collaborative")
      : t("detail.offline.nonCollaborative");
    toast.warning(message, { id: TOAST_ID, duration: Infinity });
    return () => {
      toast.dismiss(TOAST_ID);
    };
  }, [isOnline, collaboration.isCollaborating, t]);

  // Every save the user asks for by hand — the Save button, Ctrl+S, a featured
  // image change — goes through here. While the editing room is live it is
  // the writer of the content column and refuses a body sent any other way,
  // so the body goes to the room and the PATCH carries only the rest, the
  // same split the autosave makes. Whether to save while one is already in
  // flight is the caller's call: the buttons hold off, an image change does
  // not, because it is the only save that change would get.
  const saveNow = useCallback(
    (overrides?: { featured_image_url?: string | null }) => {
      if (!canEditFile) return;
      const payload = {
        name: title?.trim(),
        featured_image_url: featuredImageUrl,
        ...overrides,
      };
      if (collaboration.isCollaborating) {
        saveFile.mutate(payload);
        return;
      }
      saveFile.mutate({ ...payload, content: contentForSave });
    },
    [canEditFile, saveFile, title, featuredImageUrl, contentForSave, collaboration.isCollaborating]
  );

  const setFeaturedImage = useCallback(
    (url: string | null) => {
      setFeaturedImageUrl(url);
      isAutosaveRef.current = true;
      saveNow({ featured_image_url: url });
    },
    [saveNow]
  );
  // What the editor's pictures can be made: only a writer's.
  const featuredImage = useMemo(
    () => (canEditFile ? { url: featuredImageUrl, set: setFeaturedImage } : null),
    [canEditFile, featuredImageUrl, setFeaturedImage]
  );

  // Ctrl+S / Cmd+S manual save shortcut
  useEffect(() => {
    if (!canEditFile) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "s" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (!saveFile.isPending) saveNow();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [canEditFile, saveFile.isPending, saveNow]);

  const handleFeaturedImageChange = async (file: File) => {
    if (!canEditFile) {
      return;
    }
    if (!file.type.startsWith("image/")) {
      toast.error(t("detail.imageFileRequired"));
      return;
    }
    setIsUploadingFeaturedImage(true);
    try {
      const response = await uploadAttachment(communityId, file);
      setFeaturedImage(response.url);
      toast.success(t("detail.imageUploaded"));
    } catch (error) {
      console.error(error);
      toast.error(t("detail.imageUploadError"));
    } finally {
      setIsUploadingFeaturedImage(false);
    }
  };

  if (fileQuery.isLoading) {
    return <FileDetailSkeleton label={t("detail.loading")} />;
  }

  if (fileQuery.isError || !file) {
    return (
      <ToolAccessStatus
        error={fileQuery.error}
        keys="files:detail."
        backTo={gp(toolListRoute(Tool.file, initiativeId))}
        backLabel={t("detail.backToFiles")}
        entity={{ kind: "file", id: parsedId }}
      />
    );
  }

  const { Body, Actions, framed, editable, prose } = fileBody(file.file_type);
  // A picture or a video is shown as itself, so it takes no featured image.
  const showsItself = file.kind === FileKind.image || file.kind === FileKind.video;
  const showSummaryTab = prose && isAIEnabled;
  const body = (
    <Suspense
      fallback={
        <div className={cn("flex h-96 items-center justify-center", framed && "rounded-xl border")}>
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      }
    >
      {/* Keyed by file alone: entering collaborative mode does not remount —
          the CollaborationPlugin syncs the existing content to Yjs. */}
      <Body
        key={file.id}
        file={file}
        saved={saved}
        canEdit={canEditFile}
        collaboration={collaboration}
        live={collaborationEnabled && collaboration.isReady}
        settled={fileQuery.isFetchedAfterMount}
        title={title}
        className={cn(isFullscreen && "h-full max-h-none min-h-0 flex-1")}
        onChange={handleBodyChange}
      />
    </Suspense>
  );

  return (
    <div className="space-y-6">
      <ToolPageHeader
        tool={Tool.file}
        initiativeId={file.initiative_id}
        starId={file.id}
        settingsTo={canEditFile ? toolSettingsRoute(Tool.file, initiativeId, file.id) : undefined}
        chest={
          <ToolChest
            tool={Tool.file}
            entity={file}
            template={{
              isTemplate: file.is_template,
              onChange: (isTemplate) => setTemplate.mutateAsync({ is_template: isTemplate }),
            }}
          >
            <ToolChestSegment label={t("detail.updatedLabel")}>
              <span>{relativeUpdatedAt}</span>
            </ToolChestSegment>
            <ToolChestSegment label={t("collections.heading")}>
              <FileCollections file={file} />
            </ToolChestSegment>
            {showSummaryTab ? (
              <ToolChestSegment>
                <Button
                  variant={sidePanel.isOpen ? "secondary" : "outline"}
                  size="sm"
                  onClick={sidePanel.toggle}
                  title={sidePanel.isOpen ? t("detail.closePanel") : t("detail.openPanel")}
                >
                  <PanelRight className="h-4 w-4" />
                  <span className="sr-only">{t("detail.togglePanel")}</span>
                </Button>
              </ToolChestSegment>
            ) : null}
          </ToolChest>
        }
        title={
          // The name stays an open field: the collaboration room keeps it in
          // step with everyone editing the file.
          <span className="flex items-center gap-2">
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onFocus={() => setTitleHasFocus(true)}
              onBlur={() => setTitleHasFocus(false)}
              placeholder={t("detail.titlePlaceholder")}
              aria-label={t("detail.titlePlaceholder")}
              className="field-sizing-content h-auto w-auto min-w-0 max-w-full font-semibold text-3xl tracking-tight md:text-3xl"
              disabled={!canEditFile}
            />
            {titleIsDirty ? (
              <Button
                type="button"
                size="sm"
                onClick={() => {
                  if (!saveFile.isPending) saveNow();
                }}
                disabled={saveFile.isPending}
                className="shrink-0"
              >
                {saveFile.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                {t("common:save")}
              </Button>
            ) : null}
          </span>
        }
      />

      <FeaturedImageProvider value={featuredImage}>
        <div className="space-y-6">
          {showsItself ? null : (
            <FileFeaturedImage
              url={featuredImageUrl}
              canEdit={canEditFile}
              uploading={isUploadingFeaturedImage}
              onUpload={handleFeaturedImageChange}
              initiativeId={file.initiative_id}
              onChoose={setFeaturedImage}
              onRemove={() => setFeaturedImage(null)}
            />
          )}

          {framed ? (
            // Scoped to the body editor alone: a comment composer further down
            // the page is an editor too, and its headings are not this
            // file's contents.
            <DocumentOutlineScope>
              <div
                className={cn(
                  "flex flex-col gap-4",
                  isFullscreen && "fixed inset-0 z-50 m-0! overflow-hidden bg-background p-4"
                )}
              >
                {/* Collaboration status - shown between featured image and editor.
                  Also shown when offline even in non-collaborative mode, so the
                  user sees an explicit offline indicator at the top of the editor. */}
                {/* Wraps rather than overflows: the row carries up to four
                  controls and none of them shrink. */}
                <div className="flex flex-wrap items-center gap-2">
                  {prose && (
                    <Button
                      type="button"
                      variant={outline.isOpen ? "secondary" : "ghost"}
                      size="sm"
                      onClick={outline.toggle}
                      aria-expanded={outline.isOpen}
                      title={t(outline.isOpen ? "outline.hide" : "outline.show")}
                    >
                      <ListTree className="h-4 w-4" />
                      {t("editor:outline.title")}
                    </Button>
                  )}
                  {(joinsRoom || !isOnline) && (
                    <CollaborationStatusBadge
                      connectionStatus={collaboration.connectionStatus}
                      collaborators={collaboration.collaborators}
                      isCollaborating={collaboration.isCollaborating}
                      isSynced={collaboration.isSynced}
                      isOnline={isOnline}
                    />
                  )}
                  {Actions ? <Actions file={file} /> : null}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setIsFullscreen((value) => !value)}
                    aria-label={t(
                      isFullscreen ? "detail.exitFullscreen" : "detail.enterFullscreen"
                    )}
                    className={cn(!Actions && "ml-auto")}
                  >
                    {isFullscreen ? (
                      <Minimize2 className="h-4 w-4" />
                    ) : (
                      <Maximize2 className="h-4 w-4" />
                    )}
                    {t(isFullscreen ? "detail.exitFullscreen" : "detail.enterFullscreen")}
                  </Button>
                </div>
                <div className={cn("flex min-w-0 gap-4", isFullscreen && "min-h-0 flex-1")}>
                  {prose && (
                    <DocumentOutlinePanel
                      isOpen={outline.isOpen}
                      onOpenChange={outline.setIsOpen}
                      className={cn(
                        "hidden w-64 shrink-0 md:flex",
                        isFullscreen ? "min-h-0" : "max-h-[80vh]"
                      )}
                    />
                  )}
                  <div className={cn("flex min-w-0 flex-1 flex-col", isFullscreen && "min-h-0")}>
                    {body}
                  </div>
                </div>
                {editable ? (
                  <div className="flex flex-wrap items-center gap-3">
                    {canEditFile ? (
                      <>
                        {/* When collaboration is active, changes sync in real-time */}
                        {collaboration.isCollaborating ? (
                          <span className="text-muted-foreground text-sm">
                            {t("detail.collaborationDescription")}
                          </span>
                        ) : (
                          <>
                            <Button
                              type="button"
                              onClick={() => saveNow()}
                              disabled={!isDirty || saveFile.isPending}
                            >
                              {saveFile.isPending ? (
                                <>
                                  <Loader2 className="h-4 w-4 animate-spin" />
                                  {t("detail.saving")}
                                </>
                              ) : (
                                t("detail.saveChanges")
                              )}
                            </Button>
                            <div className="flex items-center gap-2">
                              <Checkbox
                                id="autosave"
                                checked={autosaveEnabled}
                                onCheckedChange={(checked) => setAutosaveEnabled(checked === true)}
                              />
                              <Label htmlFor="autosave" className="cursor-pointer text-sm">
                                {t("detail.autosave")}
                              </Label>
                            </div>
                            {!isDirty ? (
                              <span className="self-center text-muted-foreground text-sm">
                                {t("detail.allChangesSaved")}
                              </span>
                            ) : null}
                          </>
                        )}
                        {/* Always show collaboration toggle */}
                        <div className="flex items-center gap-2">
                          <Checkbox
                            id="collaboration"
                            checked={collaborationEnabled}
                            onCheckedChange={(checked) => setCollaborationEnabled(checked === true)}
                          />
                          <Label htmlFor="collaboration" className="cursor-pointer text-sm">
                            {t("detail.liveCollaboration")}
                          </Label>
                        </div>
                      </>
                    ) : (
                      <p className="text-muted-foreground text-sm">{t("detail.readOnly")}</p>
                    )}
                  </div>
                ) : null}
              </div>
            </DocumentOutlineScope>
          ) : (
            body
          )}

          {/* Everything this file is connected to, in place of a read-only
            list of projects and a read-only list of backlinks. The projects half
            was editable only from the project's side, which meant the same fact
            had two renderings and one of them could not be changed. */}
          <ToolRelationsPanel
            tool={Tool.file}
            entity={file}
            canEdit={canEditFile}
            entityTitle={file.name}
          />

          {/* The thread, at the width of the file it is about — the same
            place every other tool puts it. */}
          <ToolCommentsPanel
            tool={Tool.file}
            entity={file}
            onCountChange={updateFileCommentCount}
          />
        </div>
      </FeaturedImageProvider>

      {/* Side panel for the AI summary */}
      {showSummaryTab && (
        <SummarySheet
          open={sidePanel.isOpen}
          onOpenChange={sidePanel.setIsOpen}
          request={(options, signal) => generateSummary(communityId, parsedId, options, signal)}
          summary={aiSummary}
          onSummaryChange={setAiSummary}
        />
      )}
    </div>
  );
};

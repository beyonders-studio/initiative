/**
 * Whiteboard file editor backed by Excalidraw.
 *
 * - Scene data is stored in `file.content` as {elements, appState, files}.
 * - When `yDoc` is provided, the scene is also kept in the doc, one entry per
 *   element (`whiteboardRoom.ts`), so multiple clients stay in sync via the
 *   existing collaboration WebSocket pipeline. An edit sends only the elements
 *   it changed, and concurrent edits are settled per element by version.
 * - When `yDoc` is null, edits flow through the parent's REST autosave path.
 */

import {
  CaptureUpdateAction,
  Excalidraw,
  hashElementsVersion,
  reconcileElements,
  restoreElements,
  serializeAsJSON,
} from "@excalidraw/excalidraw";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import "@excalidraw/excalidraw/index.css";

import type { RemoteExcalidrawElement } from "@excalidraw/excalidraw/data/reconcile";
import type {
  ExcalidrawElement,
  OrderedExcalidrawElement,
} from "@excalidraw/excalidraw/element/types";
import type {
  AppState,
  BinaryFiles,
  ExcalidrawImperativeAPI,
  ExcalidrawInitialDataState,
} from "@excalidraw/excalidraw/types";
import type { ProviderAwareness } from "@lexical/yjs";
import type * as Y from "yjs";

import { useTheme } from "@/hooks/useTheme";
import { useWhiteboardCursors } from "@/hooks/useWhiteboardCursors";
import { cn } from "@/ui/lib/utils";
import { renderEmbeddable, validateEmbeddable } from "@/ui/lib/whiteboardEmbeds";

import {
  changedKeys,
  newestOver,
  pruneRoom,
  type RoomMaps,
  readRoomAppState,
  readRoomElements,
  readRoomFiles,
  roomHoldsScene,
  roomMaps,
  writeToRoom,
} from "./whiteboardRoom";

export interface WhiteboardScene {
  elements: readonly ExcalidrawElement[];
  appState: Partial<AppState>;
  files: BinaryFiles;
}

export interface WhiteboardFileEditorProps {
  /** Initial scene loaded from file.content (may be empty). */
  initialScene: WhiteboardScene;
  /** True if initialScene came from the localStorage write-ahead cache,
   *  meaning the user has unsaved local edits. When true, the bootstrap
   *  must NOT overwrite the canvas with Yjs sync state, which would clobber
   *  the unsaved work. When false, the bootstrap is free to apply Yjs
   *  state to catch up to a live room where another user has been
   *  editing. */
  initialSceneFromCache?: boolean;
  /** Called on every change with the pruned, persistable scene.
   *  ``isLocal`` is false when the change is a remote-applied update (or
   *  an echo of one) — the parent needs those to keep the periodic REST
   *  content-sync fresh, but must not treat them as unsaved local work
   *  (e.g. for the write-ahead cache). */
  onSerializedChange: (scene: WhiteboardScene, opts?: { isLocal: boolean }) => void;
  readOnly?: boolean;
  className?: string;
  /** Live collaboration: an already-attached Yjs doc. Null => REST-only mode. */
  yDoc?: Y.Doc | null;
  /** Whether the Yjs provider has fully synced from the server. */
  isSynced?: boolean;
  /** True if other users are currently connected to the same Yjs room.
   *  When true AND initialSceneFromCache is true, the cache is considered
   *  stale (another user has continued editing while we were gone) and
   *  the Yjs state wins on bootstrap. */
  hasOtherCollaborators?: boolean;
  /** True once the server's collaborator roster has arrived. The bootstrap
   *  decision reads ``hasOtherCollaborators``, and the roster lands on the
   *  socket *after* the sync message — deciding at the moment ``isSynced``
   *  flips would always see an empty roster and mistake a live room for an
   *  empty one. Defaults to true for REST-only mode. */
  collaboratorsReady?: boolean;
  /** Yjs awareness for peer cursor presence. Null in REST-only mode. */
  awareness?: ProviderAwareness | null;
  /** Current user for the cursor label + color. Null-safe. */
  currentUser?: { id: number; name: string } | null;
}

/**
 * Build a stable initial data object that only changes when the scene's
 * identity changes. Excalidraw treats `initialData` as a load-once hint — we
 * never pass a new reference after the first render.
 */
function makeInitialData(scene: WhiteboardScene): ExcalidrawInitialDataState {
  const hasContent = Array.isArray(scene.elements) && scene.elements.length > 0;
  return {
    elements: hasContent ? (scene.elements as OrderedExcalidrawElement[]) : [],
    appState: scene.appState ?? {},
    files: scene.files ?? {},
    scrollToContent: hasContent,
  };
}

export function WhiteboardFileEditor({
  initialScene,
  initialSceneFromCache = false,
  onSerializedChange,
  readOnly = false,
  className,
  yDoc = null,
  isSynced = true,
  hasOtherCollaborators = false,
  collaboratorsReady = true,
  awareness = null,
  currentUser = null,
}: WhiteboardFileEditorProps) {
  const { t } = useTranslation("files");
  const { resolvedTheme } = useTheme();

  const excalidrawAPIRef = useRef<ExcalidrawImperativeAPI | null>(null);
  // Mirrors the ref as state so effects that must not run before Excalidraw
  // is ready (the post-sync bootstrap, peer cursors) re-fire when the API
  // arrives — the imperative callback can land before or after the provider
  // reports synced, and a ref alone can't re-trigger an effect.
  const [excalidrawAPI, setExcalidrawAPI] = useState<ExcalidrawImperativeAPI | null>(null);
  const roomRef = useRef<RoomMaps | null>(null);
  // What the last onChange saw of the scene's persisted parts: element
  // versions, persisted app state and files. Excalidraw calls onChange on
  // every render — pointer moves, selection, peer cursors — and an unchanged
  // fingerprint skips the scene's serialization and the room scan for those.
  const lastChangeKeyRef = useRef<string>("");
  // Tracks which Y.Doc we've already bootstrapped so we don't seed twice
  // (e.g. if isSynced flips false → true → false → true on reconnect).
  const seededForDocRef = useRef<Y.Doc | null>(null);
  // Gated true AFTER the post-sync bootstrap. Remote changes are skipped
  // until then: the bootstrap reads the whole room once it has decided
  // whether the room or the scene on screen wins.
  const bootstrapDoneRef = useRef(false);
  // Separate gate for LOCAL → Yjs writes. Set true after the bootstrap
  // effect has made its decision (apply Yjs state vs keep cached scene).
  // Without this gate, Excalidraw's first onChange on mount would write
  // the initial scene to Yjs, which in the rejoin case would clobber a
  // live room's state with our stale local cache — poisoning the room
  // for all other connected users.
  const writesAllowedRef = useRef(false);

  const collaborative = Boolean(yDoc);

  // Peer cursor presence via Yjs awareness. No-op when awareness is null
  // (REST-only mode) or when enabled is false.
  const { collaborators: peerCollaborators, publishPointer } = useWhiteboardCursors({
    awareness,
    clientId: yDoc?.clientID ?? null,
    user: currentUser,
    enabled: collaborative,
  });

  // Excalidraw's onPointerUpdate fires with scene coords (post pan/zoom), so
  // each viewer re-projects through their own transform — no translation needed.
  const handlePointerUpdate = useCallback(
    (payload: {
      pointer: { x: number; y: number; tool: "pointer" | "laser" };
      button: "down" | "up";
    }) => {
      publishPointer(payload.pointer, payload.button);
    },
    [publishPointer]
  );

  // Push peer cursors into Excalidraw via updateScene. `collaborators` isn't
  // a direct prop — it lives in AppState and is updated imperatively. Passing
  // via updateScene won't generate a history entry (CaptureUpdateAction.NEVER)
  // and, importantly, won't mirror the peer map back into our serialized scene
  // because handleExcalidrawChange uses the "database" serializer which strips
  // ephemeral appState fields including collaborators.
  useEffect(() => {
    if (!excalidrawAPI) return;
    excalidrawAPI.updateScene({
      collaborators: peerCollaborators,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
  }, [peerCollaborators, excalidrawAPI]);

  // Only compute initialData once per mount (the Excalidraw key in the parent
  // forces remount on file switch, so this is safe).
  const initialData = useMemo(() => makeInitialData(initialScene), [initialScene]);

  // ── Yjs binding ───────────────────────────────────────────────────────
  //
  // NOTE ON BOOTSTRAP: we intentionally do NOT write to the room here. When
  // the user reconnects to an existing file, the provider's initial sync
  // brings in any server-side updates that happened while they were away.
  // Writing the stale `initialScene` before sync completes would race with
  // that incoming state. The bootstrap happens later in a separate effect
  // gated on `isSynced`.
  useEffect(() => {
    if (!yDoc) return;
    const maps = roomMaps(yDoc);
    roomRef.current = maps;
    // Reset bootstrap guards whenever the Y.Doc changes (e.g. navigating
    // between whiteboards).
    seededForDocRef.current = null;
    bootstrapDoneRef.current = false;

    const handleRemoteChange = (transaction: Y.Transaction) => {
      // Skip our own writes — Excalidraw already has them.
      if (transaction.local || !bootstrapDoneRef.current) return;
      const api = excalidrawAPIRef.current;
      if (!api) return;
      const changedElements = changedKeys(transaction, maps.elements);
      const changedFiles = changedKeys(transaction, maps.files);
      const changedAppState = changedKeys(transaction, maps.appState);
      if (!changedElements && !changedFiles && !changedAppState) return;
      try {
        // Add files FIRST, then update the scene. If we reversed this order,
        // Excalidraw would see image elements referencing fileIds that aren't
        // in the files map yet and lock in placeholder rendering — later
        // addFiles calls don't re-trigger those elements to repaint.
        if (changedFiles) {
          const files = readRoomFiles(maps, changedFiles);
          if (files.length > 0) api.addFiles(files);
        }
        // Only the elements that changed: anything newer locally, or still
        // being drawn here, keeps the local copy. A removed key is an expired
        // tombstone, which the scene already holds as deleted.
        const elements = changedElements
          ? reconcileElements(
              api.getSceneElementsIncludingDeleted(),
              restoreElements(
                readRoomElements(maps, changedElements),
                null
              ) as RemoteExcalidrawElement[],
              api.getAppState()
            )
          : undefined;
        api.updateScene({
          elements,
          // Cast is safe: Excalidraw only merges the subset of fields we pass.
          appState: changedAppState
            ? (readRoomAppState(maps) as Partial<AppState> as AppState)
            : undefined,
          captureUpdate: CaptureUpdateAction.NEVER,
        });
        // Two people writing one element at once leave the room holding
        // whichever write Yjs ordered last, not the higher version. Where the
        // local copy won the reconcile, the canvas did not change, so nothing
        // else would write it back: hand it to the room here.
        if (changedElements) {
          queueMicrotask(() => {
            if (!writesAllowedRef.current) return;
            writeToRoom(
              yDoc,
              maps,
              api
                .getSceneElementsIncludingDeleted()
                .filter((element) => changedElements.has(element.id)),
              {},
              api.getFiles()
            );
          });
        }
      } catch (err) {
        console.error("Failed to apply remote whiteboard update:", err);
      }
    };

    yDoc.on("afterTransaction", handleRemoteChange);
    return () => {
      yDoc.off("afterTransaction", handleRemoteChange);
      roomRef.current = null;
    };
  }, [yDoc]);

  // ── Local change handler ─────────────────────────────────────────────
  // Excalidraw fires onChange on every re-render, so anything that has not
  // changed what is persisted is skipped by its fingerprint first.
  //
  // The parent is told about remote-applied changes too: without that, its
  // whiteboardScene state never updates with them, and the periodic REST
  // content-sync would PATCH a stale local snapshot. `isLocal` tells it
  // whether this was the user's own work.
  const handleExcalidrawChange = useCallback(
    (elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      // Excalidraw's "database" serializer keeps only the app state a saved
      // scene carries (background, grid, …), not selection, zoom or cursors.
      const persistedAppState = (
        JSON.parse(serializeAsJSON([], appState, {}, "database")) as WhiteboardScene
      ).appState;
      const changeKey = [
        hashElementsVersion(elements),
        elements.length,
        Object.keys(files).length,
        JSON.stringify(persistedAppState),
      ].join(":");
      if (changeKey === lastChangeKeyRef.current) return;
      lastChangeKeyRef.current = changeKey;

      // Mirror to Yjs when collaborative — but only after the bootstrap has
      // decided whether to keep our cached scene or override with the live
      // room state. Writing on the initial mount onChange would broadcast
      // our (possibly stale) local cache to the room and clobber other
      // users' live edits. Only what is newer than the room's copy is
      // written, so a remote change applied here writes nothing back.
      const room = roomRef.current;
      const wrote =
        yDoc && room && writesAllowedRef.current
          ? writeToRoom(yDoc, room, elements, persistedAppState, files)
          : false;

      // NOTE: the "database" mode deliberately strips the files map — it
      // sets `files: undefined` in the output — so we merge the binaries
      // back in manually below. Otherwise images would round-trip as empty
      // frames.
      const scene = JSON.parse(
        serializeAsJSON(elements, appState, files, "database")
      ) as WhiteboardScene;
      // Only keep file entries that are still referenced by an element so
      // deleted images don't bloat storage forever.
      const filteredFiles: BinaryFiles = {};
      for (const el of elements) {
        const fileId = (el as { fileId?: string | null }).fileId;
        if (fileId && !el.isDeleted && files[fileId]) filteredFiles[fileId] = files[fileId];
      }
      scene.files = filteredFiles;

      onSerializedChange(scene, { isLocal: collaborative ? wrote : true });
    },
    [onSerializedChange, yDoc, collaborative]
  );

  // ── Post-sync bootstrap ──────────────────────────────────────────────
  // After initial Yjs sync, decide whether to apply the room's state to
  // Excalidraw. Three cases:
  //
  // • Other users connected: the room is live and authoritative — apply
  //   the room's state regardless of whether our initialScene came from
  //   cache or REST. A stale local cache (from a previous visit where
  //   another user kept editing after we left) must NOT be propagated
  //   to Yjs, or we'd clobber the live room's state for all users.
  //
  // • initialSceneFromCache === true AND alone: we have unsaved local
  //   edits and no one else is here to correct us. Keep the cached scene
  //   (the Yjs state is likely behind by one edit because the last
  //   WebSocket message was lost on page unload), and write it into the
  //   room over what it holds: the room renders the saved scene from its
  //   Yjs state, so that is what saves it.
  //
  // • initialSceneFromCache === false AND alone: no unsaved local work.
  //   Apply the room's state if it has anything — it may be more recent
  //   than the REST content (e.g. from a `persist_room` snapshot that
  //   happened after the last REST PATCH).
  //
  // After the decision, flip writesAllowedRef so subsequent local edits
  // flow to Yjs, and bootstrapDoneRef so remote updates flow in.
  useEffect(() => {
    // Wait for the collaborator roster as well as the sync: the roster
    // arrives on the socket right after the sync message, and deciding
    // before it lands would read hasOtherCollaborators as false even in
    // a live room. Wait for the Excalidraw API too — this effect can win
    // the race against Excalidraw's mount callback, and completing the
    // bootstrap without applying the room state would arm writes while
    // the canvas still shows the REST snapshot: the mount onChange would
    // then push that older scene into the live room and roll every other
    // user back to it.
    if (!yDoc || !isSynced || !collaboratorsReady || !excalidrawAPI) return;
    if (seededForDocRef.current === yDoc) return;
    seededForDocRef.current = yDoc;
    const maps = roomMaps(yDoc);

    const shouldApplyYjsState = hasOtherCollaborators || !initialSceneFromCache;

    try {
      if (shouldApplyYjsState && roomHoldsScene(maps)) {
        const files = readRoomFiles(maps);
        if (files.length > 0) excalidrawAPI.addFiles(files);
        excalidrawAPI.updateScene({
          elements: restoreElements(readRoomElements(maps), null),
          appState: readRoomAppState(maps) as Partial<AppState> as AppState,
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      } else if (!shouldApplyYjsState) {
        // Our unsaved work wins: every element the room holds a newer copy
        // of moves past it, so the write below replaces the room's.
        excalidrawAPI.updateScene({
          elements: newestOver(excalidrawAPI.getSceneElementsIncludingDeleted(), maps),
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      }
    } catch (err) {
      console.error("Failed to apply post-sync whiteboard state:", err);
    }

    bootstrapDoneRef.current = true;
    writesAllowedRef.current = true;
    pruneRoom(yDoc, maps);
    // Hand the room whatever the scene on screen has that it lacks: all of
    // it for a room that held nothing, our cached work when that won.
    const appState = excalidrawAPI.getAppState();
    writeToRoom(
      yDoc,
      maps,
      excalidrawAPI.getSceneElementsIncludingDeleted(),
      (JSON.parse(serializeAsJSON([], appState, {}, "database")) as WhiteboardScene).appState,
      excalidrawAPI.getFiles(),
      { replace: !shouldApplyYjsState }
    );
  }, [
    yDoc,
    isSynced,
    initialSceneFromCache,
    hasOtherCollaborators,
    collaboratorsReady,
    excalidrawAPI,
  ]);

  return (
    <div
      className={cn(
        "relative h-[80vh] w-full overflow-hidden rounded-lg border bg-background shadow",
        className
      )}
    >
      {/* Covered through a reconnect too, unlike a text or a sheet: the scene
          is one value in the room, so an edit made while apart would replace
          a collaborator's rather than merge with it. */}
      {collaborative && !isSynced && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-background/80">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>{t("whiteboard.syncing")}</span>
          </div>
        </div>
      )}
      <Excalidraw
        excalidrawAPI={(api) => {
          excalidrawAPIRef.current = api;
          setExcalidrawAPI(api);
        }}
        initialData={initialData}
        onChange={handleExcalidrawChange}
        onPointerUpdate={handlePointerUpdate}
        viewModeEnabled={readOnly}
        isCollaborating={collaborative}
        theme={resolvedTheme}
        validateEmbeddable={validateEmbeddable}
        renderEmbeddable={renderEmbeddable}
      />
    </div>
  );
}

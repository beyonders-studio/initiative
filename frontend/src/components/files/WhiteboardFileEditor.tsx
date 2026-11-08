/**
 * Whiteboard file editor backed by Excalidraw.
 *
 * - Scene data is stored in `file.content` as {elements, appState, files}.
 * - When `yDoc` is provided, the scene is also mirrored to a single-key Yjs
 *   map (`excalidraw.scene`) so multiple clients stay in sync via the existing
 *   collaboration WebSocket pipeline. Conflict resolution is last-write-wins at
 *   the scene key — an explicit v1 trade-off.
 * - When `yDoc` is null, edits flow through the parent's REST autosave path.
 */

import { CaptureUpdateAction, Excalidraw, serializeAsJSON } from "@excalidraw/excalidraw";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import "@excalidraw/excalidraw/index.css";

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
import { renderEmbeddable, validateEmbeddable } from "@/lib/whiteboardEmbeds";
import { cn } from "@/ui/lib/utils";

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
  const yMapRef = useRef<Y.Map<string> | null>(null);
  const applyingRemoteRef = useRef(false);
  // Tracks the most recently seen serialized scene (either a local write
  // or a freshly-applied remote update). Used by handleExcalidrawChange to
  // skip no-op propagation and by the Yjs observer to suppress the echo
  // cycle when a remote update triggers a local onChange.
  const prevSerializedRef = useRef<string>("");
  // Separate dedupe for the parent onSerializedChange callback. We need to
  // notify the parent for *both* local edits and remote-applied updates
  // (otherwise the periodic REST content-sync writes a stale snapshot —
  // see the User 2 refresh bug). But we can't notify on every echo
  // onChange or we cause an infinite render loop. This ref tracks the
  // last scene we passed up so we can skip duplicates.
  const lastNotifiedSerializedRef = useRef<string>("");
  // Tracks which Y.Doc we've already bootstrapped so we don't seed twice
  // (e.g. if isSynced flips false → true → false → true on reconnect).
  const seededForDocRef = useRef<Y.Doc | null>(null);
  // Gated true AFTER the post-sync bootstrap seeds the Y.Map. The observer
  // skips all events until this is true, so the stale initial Yjs sync
  // (from persist_room, which can be one edit behind because the last
  // WebSocket message is lost on page unload) never overwrites the correct
  // REST-fetched initialScene that Excalidraw is already displaying.
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
  // NOTE ON BOOTSTRAP: we intentionally do NOT seed the Y.Map here. When the
  // user reconnects to an existing file, the provider's initial sync
  // brings in any server-side updates that happened while they were away.
  // Seeding with the stale `initialScene` before sync completes would race
  // with that incoming state — via last-write-wins on the `scene` key, the
  // seed could clobber legitimate updates. The bootstrap happens later in
  // a separate effect gated on `isSynced`.
  useEffect(() => {
    if (!yDoc) return;
    const yMap = yDoc.getMap<string>("excalidraw");
    yMapRef.current = yMap;
    // Reset bootstrap guards whenever the Y.Doc changes (e.g. navigating
    // between whiteboards).
    seededForDocRef.current = null;
    bootstrapDoneRef.current = false;

    const handleRemoteChange = (event: Y.YMapEvent<string>) => {
      // Skip our own writes — Excalidraw already has them
      if (event.transaction.local) return;
      // Skip events from the initial Yjs sync. The server's yjs_state can
      // be one edit behind file.content (the last WebSocket message is
      // lost on page unload, while the keepalive PATCH survives). Applying
      // the stale sync state would overwrite the correct REST-fetched scene
      // that Excalidraw is already displaying. Only LIVE updates from other
      // users (which arrive after the bootstrap seeds the Y.Map) should be
      // applied.
      if (!bootstrapDoneRef.current) return;
      const raw = yMap.get("scene");
      if (!raw || !excalidrawAPIRef.current) return;
      try {
        const parsed = JSON.parse(raw) as {
          elements: readonly OrderedExcalidrawElement[];
          appState?: Partial<AppState>;
          files?: BinaryFiles;
        };
        // Critical: seed prevSerializedRef BEFORE calling updateScene.
        // Excalidraw's updateScene schedules onChange asynchronously; when
        // it fires, handleExcalidrawChange compares the serialized scene
        // to prevSerializedRef and bails out if they match — which breaks
        // the echo cycle that would otherwise interrupt the drawing user's
        // in-progress drag (e.g. a pencil stroke).
        prevSerializedRef.current = raw;
        applyingRemoteRef.current = true;

        // Add files FIRST, then update the scene. If we reversed this order,
        // Excalidraw would see image elements referencing fileIds that aren't
        // in the files map yet and lock in placeholder rendering — later
        // addFiles calls don't re-trigger those elements to repaint.
        if (parsed.files) {
          const fileArr = Object.values(parsed.files);
          if (fileArr.length > 0) {
            excalidrawAPIRef.current.addFiles(fileArr);
          }
        }

        excalidrawAPIRef.current.updateScene({
          elements: parsed.elements,
          // Cast is safe: Excalidraw only merges the subset of fields we pass.
          appState: parsed.appState as Partial<AppState> as AppState,
          captureUpdate: CaptureUpdateAction.NEVER,
        });
      } catch (err) {
        console.error("Failed to apply remote whiteboard update:", err);
        applyingRemoteRef.current = false;
        return;
      }
      // Clear the flag on a microtask so it stays set through Excalidraw's
      // async onChange callback — a synchronous reset in a finally block
      // would clear it before the echo callback runs, making the guard in
      // handleExcalidrawChange dead code. prevSerializedRef is the primary
      // dedupe; this flag is defense-in-depth against future serializer
      // changes that could desync the byte-level comparison.
      queueMicrotask(() => {
        applyingRemoteRef.current = false;
      });
    };

    yMap.observe(handleRemoteChange);
    return () => {
      yMap.unobserve(handleRemoteChange);
      yMapRef.current = null;
    };
  }, [yDoc]);

  // ── Local change handler ─────────────────────────────────────────────
  // Excalidraw fires onChange on every re-render (unlike Lexical which
  // debounces internally). We must skip Yjs writes when the serialized
  // scene hasn't actually changed, otherwise we cause an infinite loop:
  // onChange → setWhiteboardScene → re-render → onChange → …
  //
  // CRUCIAL: we must still call `onSerializedChange` for remote-triggered
  // onChange events (where applyingRemoteRef is set or the dedupe matches).
  // Without that, the parent's whiteboardScene state never updates with
  // remote changes, causing the periodic 10s REST content-sync to PATCH a
  // stale local snapshot — which eventually rolls user 1's view backward
  // and corrupts what gets persisted to file.content for refreshes.
  const handleExcalidrawChange = useCallback(
    (elements: readonly OrderedExcalidrawElement[], appState: AppState, files: BinaryFiles) => {
      // Use Excalidraw's "database" serializer to strip ephemeral appState
      // (selection, collaborators, cursor, zoom-to-fit, etc.). NOTE: this
      // mode deliberately strips the files map — it sets `files: undefined`
      // in the output — so we merge the binaries back in manually below.
      // Otherwise images would round-trip as empty frames.
      const serialized = serializeAsJSON(elements, appState, files, "database");
      const parsed = JSON.parse(serialized) as WhiteboardScene;

      // Only keep file entries that are still referenced by an element so
      // deleted images don't bloat storage forever.
      const referencedFileIds = new Set<string>();
      for (const el of elements) {
        const maybeFileId = (el as { fileId?: string | null }).fileId;
        if (maybeFileId) referencedFileIds.add(maybeFileId);
      }
      const filteredFiles: BinaryFiles = {};
      for (const [id, file] of Object.entries(files)) {
        if (referencedFileIds.has(id)) filteredFiles[id] = file;
      }
      parsed.files = filteredFiles;

      // Re-serialize with files present for the dedupe comparisons and
      // downstream writes.
      const serializedWithFiles = JSON.stringify(parsed);

      // An echo is an onChange for state we already know about: either
      // we're mid-apply of a remote update, or the serialized scene matches
      // what we last saw (local or remote).
      const isEcho = applyingRemoteRef.current || serializedWithFiles === prevSerializedRef.current;

      // Notify the parent only when the serialized scene actually changed
      // since the last notification. This dedupe is independent of the Yjs
      // dedupe below: we want the parent to see remote-applied updates
      // (so REST content-sync isn't stale), but we must not call the
      // parent on every echo render or we cause an infinite loop. The
      // isLocal flag lets the parent treat only genuine local edits as
      // unsaved work.
      if (serializedWithFiles !== lastNotifiedSerializedRef.current) {
        lastNotifiedSerializedRef.current = serializedWithFiles;
        onSerializedChange(parsed, { isLocal: !isEcho });
      }

      // Skip the Yjs write for echoes — writing them back to Yjs would
      // interrupt the original sender's in-progress drag.
      if (isEcho) return;
      prevSerializedRef.current = serializedWithFiles;

      // Mirror to Yjs when collaborative — but only after the bootstrap has
      // decided whether to keep our cached scene or override with the live
      // room state. Writing on the initial mount onChange would broadcast
      // our (possibly stale) local cache to the room and clobber other
      // users' live edits.
      if (yMapRef.current && writesAllowedRef.current) {
        yMapRef.current.set("scene", serializedWithFiles);
      }
    },
    [onSerializedChange]
  );

  // ── Post-sync bootstrap ──────────────────────────────────────────────
  // After initial Yjs sync, decide whether to apply the Y.Map state to
  // Excalidraw. Three cases:
  //
  // • Other users connected: the room is live and authoritative — apply
  //   the Y.Map state regardless of whether our initialScene came from
  //   cache or REST. A stale local cache (from a previous visit where
  //   another user kept editing after we left) must NOT be propagated
  //   to Yjs, or we'd clobber the live room's state for all users.
  //
  // • initialSceneFromCache === true AND alone: we have unsaved local
  //   edits and no one else is here to correct us. Keep the cached scene
  //   (the Yjs state is likely behind by one edit because the last
  //   WebSocket message was lost on page unload), and write it into the
  //   room: the room renders the saved scene from its Yjs state, so that
  //   is what saves it.
  //
  // • initialSceneFromCache === false AND alone: no unsaved local work.
  //   Apply the Y.Map state if it has anything — it may be more recent
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

    const shouldApplyYjsState = hasOtherCollaborators || !initialSceneFromCache;

    if (shouldApplyYjsState) {
      const yMap = yDoc.getMap<string>("excalidraw");
      const raw = yMap.get("scene");
      if (raw) {
        try {
          const parsed = JSON.parse(raw) as {
            elements: readonly OrderedExcalidrawElement[];
            appState?: Partial<AppState>;
            files?: BinaryFiles;
          };
          prevSerializedRef.current = raw;
          applyingRemoteRef.current = true;
          if (parsed.files) {
            const fileArr = Object.values(parsed.files);
            if (fileArr.length > 0) {
              excalidrawAPI.addFiles(fileArr);
            }
          }
          excalidrawAPI.updateScene({
            elements: parsed.elements,
            appState: parsed.appState as Partial<AppState> as AppState,
            captureUpdate: CaptureUpdateAction.NEVER,
          });
          queueMicrotask(() => {
            applyingRemoteRef.current = false;
          });
        } catch (err) {
          console.error("Failed to apply post-sync whiteboard state:", err);
          applyingRemoteRef.current = false;
        }
      }
    }

    bootstrapDoneRef.current = true;
    writesAllowedRef.current = true;
    if (!shouldApplyYjsState) {
      // The canvas already shows this scene, so it reads as an echo; clearing
      // the last one seen sends it.
      prevSerializedRef.current = "";
      handleExcalidrawChange(
        excalidrawAPI.getSceneElementsIncludingDeleted(),
        excalidrawAPI.getAppState(),
        excalidrawAPI.getFiles()
      );
    }
  }, [
    yDoc,
    isSynced,
    initialSceneFromCache,
    hasOtherCollaborators,
    collaboratorsReady,
    excalidrawAPI,
    handleExcalidrawChange,
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

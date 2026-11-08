/**
 * Hiding parts of a picture and marking what is wrong, before it is attached.
 *
 * A picture of the page shows the page's copy (`lib/pagePicture`): pointing
 * outlines the part under the pointer and names it, a click paints it over or
 * marks it, and dragging covers any area. The people on it start swapped for
 * stand-ins where the box says so, and one switch shows them again. A picture
 * from elsewhere has no parts to point at, so it is dragged over.
 *
 * Attaching draws a fresh picture: what was painted over is painted into it,
 * and nothing else the file carried goes with it.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  blankAvatar,
  PART_SELECTOR,
  type PagePicture,
  type PartKind,
  type PeopleOnPage,
  partKindOf,
  type Rect,
  showPeople,
  svgImage,
} from "@/lib/pagePicture";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { cn } from "@/ui/lib/utils";
import { Switch } from "@/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/ui/toggle-group";

/** What hiding paints, and what a mark is drawn in: the same on screen as in
 *  the picture sent. */
const HIDE = "#8b919c";
const MARK = "#ea580c";

type Tool = "hide" | "mark";

interface Shape {
  tool: Tool;
  rect: Rect;
  /** The part of the page it covers, measured again when people are shown
   *  or hidden; none for an area drawn by hand. */
  part: Element | null;
}

export type PictureSource =
  | { kind: "page"; picture: PagePicture; people: PeopleOnPage }
  | { kind: "file"; file: File };

/** What the editor holds for one picture, kept with it once attached so it
 *  opens again where it was left. */
export interface PictureSession {
  source: PictureSource;
  shapes: Shape[];
  peopleHidden: boolean;
}

export const newSession = (source: PictureSource, peopleHidden = false): PictureSession => ({
  source,
  shapes: [],
  peopleHidden,
});

interface PictureEditorProps {
  session: PictureSession;
  /** Already attached: it opens with Done, and Cancel keeps it as it was. */
  attached: boolean;
  /** Take the picture made, with what made it; or say why it is not taken,
   *  and the editor stays open. */
  onDone: (file: File, kept: Pick<PictureSession, "shapes" | "peopleHidden">) => string | null;
  onCancel: () => void;
}

const contains = (rect: Rect, x: number, y: number) =>
  x >= rect.x && x <= rect.x + rect.w && y >= rect.y && y <= rect.y + rect.h;

const between = (a: { x: number; y: number }, b: { x: number; y: number }): Rect => ({
  x: Math.min(a.x, b.x),
  y: Math.min(a.y, b.y),
  w: Math.abs(a.x - b.x),
  h: Math.abs(a.y - b.y),
});

const place = (rect: Rect, scale = 1) => ({
  left: rect.x * scale,
  top: rect.y * scale,
  width: rect.w * scale,
  height: rect.h * scale,
});

/** Paint the picture: the hidden parts first, then the marks, numbered. */
const paint = (
  base: CanvasImageSource,
  size: { w: number; h: number },
  shapes: Shape[],
  ratio: number,
  type: string
): Promise<Blob> => {
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(size.w * ratio);
  canvas.height = Math.round(size.h * ratio);
  const context = canvas.getContext("2d");
  if (!context) return Promise.reject(new Error("No canvas to draw on."));
  context.scale(ratio, ratio);
  context.drawImage(base, 0, 0, size.w, size.h);
  context.fillStyle = HIDE;
  for (const { rect } of shapes.filter((shape) => shape.tool === "hide")) {
    context.beginPath();
    context.roundRect(rect.x, rect.y, rect.w, rect.h, 5);
    context.fill();
  }
  shapes
    .filter((shape) => shape.tool === "mark")
    .forEach(({ rect }, index) => {
      context.beginPath();
      context.roundRect(rect.x, rect.y, rect.w, rect.h, 9);
      context.lineWidth = 3;
      context.strokeStyle = MARK;
      context.stroke();
      context.beginPath();
      context.arc(rect.x, rect.y, 12, 0, Math.PI * 2);
      context.fillStyle = MARK;
      context.fill();
      context.fillStyle = "#ffffff";
      context.font = "bold 13px system-ui, sans-serif";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillText(String(index + 1), rect.x, rect.y + 0.5);
    });
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("The picture could not be made."))),
      type,
      0.92
    )
  );
};

const loadImage = (url: string): Promise<HTMLImageElement> =>
  new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The picture could not be read."));
    image.src = url;
  });

/** The most pixels a picture is painted with, which every browser's canvas
 *  holds. */
const MOST_PIXELS = 16_000_000;

/**
 * The picture a session makes, painted with its covers and marks. The page
 * becomes a PNG, at the screen's sharpness where the canvas has room; a photo
 * stays the type it was, and anything else becomes a PNG.
 */
export const makePicture = async (
  session: PictureSession,
  size: { w: number; h: number },
  pageName: string
): Promise<File> => {
  const { source, shapes } = session;
  if (source.kind === "page") {
    const ratio = Math.min(
      window.devicePixelRatio || 1,
      2,
      Math.sqrt(MOST_PIXELS / (size.w * size.h))
    );
    const blob = await paint(await svgImage(source.picture.svg), size, shapes, ratio, "image/png");
    return new File([blob], `${pageName}.png`, { type: "image/png" });
  }
  const url = URL.createObjectURL(source.file);
  try {
    const photo = ["image/jpeg", "image/webp"].includes(source.file.type);
    const type = photo ? source.file.type : "image/png";
    const blob = await paint(await loadImage(url), size, shapes, 1, type);
    const name = photo ? source.file.name : `${source.file.name.replace(/\.[^.]+$/, "")}.png`;
    return new File([blob], name, { type });
  } finally {
    URL.revokeObjectURL(url);
  }
};

export const PictureEditor = ({ session, attached, onDone, onCancel }: PictureEditorProps) => {
  const { t } = useTranslation(["intake", "common"]);
  const { source } = session;
  const page = source.kind === "page" ? source : null;
  const [shapes, setShapes] = useState<Shape[]>(session.shapes);
  const [history, setHistory] = useState<Shape[][]>([]);
  const [tool, setTool] = useState<Tool>("hide");
  const [peopleHidden, setPeopleHidden] = useState(session.peopleHidden);
  const [size, setSize] = useState(page ? { w: page.picture.width, h: page.picture.height } : null);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [scale, setScale] = useState(1);
  const [hover, setHover] = useState<{ rect: Rect; label: string } | null>(null);
  const [draft, setDraft] = useState<Rect | null>(null);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  // Held in state: the dialog draws its content after this renders, and
  // what is set up on them waits until they are there.
  const [stage, setStage] = useState<HTMLDivElement | null>(null);
  const [holder, setHolder] = useState<HTMLDivElement | null>(null);
  const drawing = useRef<HTMLDivElement>(null);
  const down = useRef<{
    from: { x: number; y: number };
    shape: number | null;
    part: Element | null;
    moved: boolean;
  } | null>(null);
  const stepped = useRef(-1);
  const blank = useMemo(blankAvatar, []);

  // A picture from elsewhere: shown from its own bytes, at its own size.
  useEffect(() => {
    if (source.kind !== "file") return;
    const url = URL.createObjectURL(source.file);
    setFileUrl(url);
    loadImage(url)
      .then((image) => setSize({ w: image.naturalWidth, h: image.naturalHeight }))
      .catch(() => setFailed(t("picture.failed")));
    return () => URL.revokeObjectURL(url);
  }, [source, t]);

  // The page's copy goes in as it is; nothing on it can be focused or used.
  useLayoutEffect(() => {
    if (!page || !holder) return;
    page.picture.svg.setAttribute("inert", "");
    holder.replaceChildren(page.picture.svg);
  }, [page, holder]);

  // The picture fits what the stage has room for, and never grows past itself.
  useLayoutEffect(() => {
    const element = stage;
    if (!element || !size) return;
    const resize = () =>
      setScale(
        Math.max(
          0.05,
          Math.min((element.clientWidth - 32) / size.w, (element.clientHeight - 32) / size.h, 1)
        )
      );
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [size, stage]);

  /** Where an element of the page's copy is, in the picture's own pixels. */
  const measure = (element: Element, pad = 0): Rect => {
    const origin = holder?.getBoundingClientRect();
    const box = element.getBoundingClientRect();
    if (!origin) return { x: 0, y: 0, w: 0, h: 0 };
    return {
      x: (box.left - origin.left) / scale - pad,
      y: (box.top - origin.top) / scale - pad,
      w: box.width / scale + pad * 2,
      h: box.height / scale + pad * 2,
    };
  };

  /** What covers a part, measured where the part is now. */
  const remeasure = (list: Shape[]) =>
    list.map((shape) =>
      shape.part ? { ...shape, rect: measure(shape.part, shape.tool === "hide" ? 2 : 5) } : shape
    );

  // People shown or hidden move what is around them: what covers a part
  // follows it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: measured again only when people change
  useLayoutEffect(() => {
    if (!page || !holder) return;
    showPeople(page.people, peopleHidden, blank);
    setShapes((current) => remeasure(current));
  }, [page, peopleHidden, blank, holder]);

  const change = (next: Shape[]) => {
    setHistory((past) => [...past, shapes]);
    setShapes(next);
  };
  const undo = () => {
    const last = history.at(-1);
    if (!last) return;
    setHistory(history.slice(0, -1));
    // The page may have moved since: what covers a part goes where it is now.
    setShapes(remeasure(last));
  };

  const partName = (part: Element) => t(`picture.parts.${partKindOf(part) as PartKind}`);
  const parts = () => (holder ? [...holder.querySelectorAll(PART_SELECTOR)] : []);
  const visible = (rect: Rect) =>
    size !== null &&
    rect.w > 0 &&
    rect.h > 0 &&
    rect.x + rect.w > 0 &&
    rect.y + rect.h > 0 &&
    rect.x < size.w &&
    rect.y < size.h;

  /** The smallest part of the page under a point. */
  const partAt = (x: number, y: number) => {
    let found: Element | null = null;
    let area = Number.POSITIVE_INFINITY;
    for (const part of parts()) {
      const rect = measure(part);
      if (visible(rect) && contains(rect, x, y) && rect.w * rect.h < area) {
        found = part;
        area = rect.w * rect.h;
      }
    }
    return found;
  };
  /** The last shape the current tool drew under a point. */
  const shapeAt = (x: number, y: number) => {
    for (let index = shapes.length - 1; index >= 0; index -= 1) {
      if (shapes[index].tool === tool && contains(shapes[index].rect, x, y)) return index;
    }
    return null;
  };

  const undoLabel = tool === "hide" ? t("picture.showAgain") : t("picture.removeMark");
  const doLabel = (part: Element) =>
    tool === "hide"
      ? t("picture.hidePart", { part: partName(part) })
      : t("picture.markPart", { part: partName(part) });

  const toggle = (part: Element) => {
    const index = shapes.findIndex((shape) => shape.tool === tool && shape.part === part);
    if (index >= 0) change(shapes.filter((_, i) => i !== index));
    else change([...shapes, { tool, rect: measure(part, tool === "hide" ? 2 : 5), part }]);
  };

  const pointAt = (event: React.PointerEvent) => {
    const box = drawing.current?.getBoundingClientRect();
    if (!box || !size) return { x: 0, y: 0 };
    return {
      x: Math.min(size.w, Math.max(0, (event.clientX - box.left) / scale)),
      y: Math.min(size.h, Math.max(0, (event.clientY - box.top) / scale)),
    };
  };

  const hoverAt = (x: number, y: number) => {
    const shape = shapeAt(x, y);
    if (shape !== null) {
      setHover({ rect: shapes[shape].rect, label: undoLabel });
      return;
    }
    const part = page ? partAt(x, y) : null;
    setHover(part ? { rect: measure(part, 3), label: doLabel(part) } : null);
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0 || !size) return;
    event.preventDefault();
    stage?.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    const { x, y } = pointAt(event);
    const shape = shapeAt(x, y);
    down.current = {
      from: { x, y },
      shape,
      part: shape === null && page ? partAt(x, y) : null,
      moved: false,
    };
  };
  const onPointerMove = (event: React.PointerEvent) => {
    const point = pointAt(event);
    const held = down.current;
    if (!held) {
      hoverAt(point.x, point.y);
      return;
    }
    if (!held.moved && Math.hypot(point.x - held.from.x, point.y - held.from.y) * scale > 6) {
      held.moved = true;
      setHover(null);
    }
    if (held.moved) setDraft(between(held.from, point));
  };
  const onPointerUp = (event: React.PointerEvent) => {
    const held = down.current;
    down.current = null;
    if (!held) return;
    if (held.moved) {
      const rect = between(held.from, pointAt(event));
      setDraft(null);
      if (rect.w * scale > 8 && rect.h * scale > 8) change([...shapes, { tool, rect, part: null }]);
      return;
    }
    setHover(null);
    if (held.shape !== null) change(shapes.filter((_, i) => i !== held.shape));
    else if (held.part) toggle(held.part);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      undo();
      return;
    }
    if (!page) return;
    const shown = parts().filter((part) => visible(measure(part)));
    if (shown.length === 0) return;
    if (event.key.startsWith("Arrow")) {
      event.preventDefault();
      const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
      stepped.current = (stepped.current + step + shown.length) % shown.length;
      const part = shown[stepped.current];
      setHover({ rect: measure(part, 3), label: doLabel(part) });
    } else if ((event.key === " " || event.key === "Enter") && shown[stepped.current]) {
      event.preventDefault();
      toggle(shown[stepped.current]);
    }
  };

  const save = async () => {
    if (!size) return;
    setSaving(true);
    try {
      const made = await makePicture(
        { ...session, shapes, peopleHidden },
        size,
        t("picture.title")
      );
      setFailed(onDone(made, { shapes, peopleHidden }));
    } catch {
      setFailed(t("picture.failed"));
    } finally {
      setSaving(false);
    }
  };

  const cancel = () => {
    // The page's copy goes back to how it was left.
    if (page) showPeople(page.people, session.peopleHidden, blank);
    onCancel();
  };

  const marks = shapes.filter((shape) => shape.tool === "mark");
  const people = page?.people;
  const hint = page
    ? tool === "hide"
      ? t("picture.hideHint")
      : t("picture.markHint")
    : tool === "hide"
      ? t("picture.hideHintFile")
      : t("picture.markHintFile");

  return (
    <Dialog open onOpenChange={(open) => !open && !saving && cancel()}>
      <DialogContent
        className="flex h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] max-w-6xl flex-col gap-0 overflow-hidden p-0 sm:max-w-6xl"
        // Enter here is the editor's: it does not reach the panel's send shortcut.
        onKeyDown={(event) => {
          if (event.key === "Enter") event.stopPropagation();
        }}
      >
        <DialogHeader className="border-b px-4 py-3 text-left">
          <DialogTitle>
            {source.kind === "page" ? t("picture.title") : source.file.name}
          </DialogTitle>
          <DialogDescription className="sr-only">{t("picture.who")}</DialogDescription>
        </DialogHeader>
        <div className="flex min-h-0 flex-1 flex-col md:flex-row">
          <div
            ref={setStage}
            role="application"
            // biome-ignore lint/a11y/noNoninteractiveTabindex: the picture is worked from the keyboard too
            tabIndex={0}
            aria-label={t("picture.surface")}
            className="relative grid min-h-0 flex-1 touch-none select-none place-items-center overflow-hidden bg-muted outline-offset-[-3px]"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={() => {
              down.current = null;
              setDraft(null);
            }}
            onPointerLeave={() => {
              if (!down.current) setHover(null);
            }}
            onKeyDown={onKeyDown}
          >
            {size ? (
              <div
                className="relative rounded-md shadow-lg outline outline-border"
                style={{ width: size.w * scale, height: size.h * scale }}
              >
                <div className="absolute inset-0 overflow-hidden rounded-md">
                  <div
                    ref={drawing}
                    className="absolute top-0 left-0 origin-top-left cursor-crosshair bg-background"
                    style={{ width: size.w, height: size.h, transform: `scale(${scale})` }}
                  >
                    {page ? (
                      <div ref={setHolder} className="pointer-events-none" />
                    ) : fileUrl ? (
                      <img
                        src={fileUrl}
                        alt=""
                        draggable={false}
                        className="pointer-events-none block h-full w-full"
                      />
                    ) : null}
                    {/* Covers first, then marks: as the picture is painted. */}
                    {[...shapes.filter((shape) => shape.tool === "hide"), ...marks].map((shape) =>
                      shape.tool === "hide" ? (
                        <div
                          key={shapes.indexOf(shape)}
                          className="pointer-events-none absolute rounded-[5px]"
                          style={{ ...place(shape.rect), background: HIDE }}
                        />
                      ) : (
                        <div
                          key={shapes.indexOf(shape)}
                          className="pointer-events-none absolute rounded-[9px] border-[3px]"
                          style={{ ...place(shape.rect), borderColor: MARK }}
                        >
                          <span
                            className="absolute -top-3.5 -left-3.5 grid size-6 place-items-center rounded-full font-bold text-[13px] text-white"
                            style={{ background: MARK }}
                          >
                            {marks.indexOf(shape) + 1}
                          </span>
                        </div>
                      )
                    )}
                  </div>
                </div>
                {hover ? (
                  <div
                    className={cn(
                      "pointer-events-none absolute z-10 rounded-md border-2",
                      tool === "hide" ? "border-foreground border-dashed" : "border-solid"
                    )}
                    style={{
                      ...place(hover.rect, scale),
                      ...(tool === "mark" ? { borderColor: MARK } : {}),
                    }}
                  >
                    <span
                      className={cn(
                        "absolute left-0 whitespace-nowrap rounded px-1.5 py-0.5 font-medium text-xs",
                        hover.rect.y * scale < 28 ? "top-full mt-1" : "bottom-full mb-1",
                        tool === "hide" ? "bg-foreground text-background" : "text-white"
                      )}
                      style={tool === "mark" ? { background: MARK } : undefined}
                    >
                      {hover.label}
                    </span>
                  </div>
                ) : null}
                {draft ? (
                  <div
                    className="pointer-events-none absolute z-10 rounded border-2 border-foreground border-dashed"
                    style={{
                      ...place(draft, scale),
                      ...(tool === "mark"
                        ? { borderColor: MARK, borderStyle: "solid" }
                        : { background: `${HIDE}b3` }),
                    }}
                  />
                ) : null}
              </div>
            ) : null}
          </div>

          <div className="grid min-h-0 content-start gap-3 overflow-y-auto border-t p-3 md:w-64 md:border-t-0 md:border-l md:p-4">
            <div className="flex items-center gap-2">
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={tool}
                onValueChange={(value) => {
                  if (value) setTool(value as Tool);
                  setHover(null);
                }}
                aria-label={t("picture.tool")}
                className="flex-1"
              >
                <ToggleGroupItem value="hide" className="flex-1">
                  {t("picture.hide")}
                </ToggleGroupItem>
                <ToggleGroupItem value="mark" className="flex-1">
                  {t("picture.mark")}
                </ToggleGroupItem>
              </ToggleGroup>
              <Button variant="ghost" size="sm" onClick={undo} disabled={history.length === 0}>
                {t("picture.undo")}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs">{hint}</p>
            {people ? (
              <div className="grid gap-2 border-t pt-3">
                <div className="flex items-center gap-2">
                  <Switch
                    id="picture-people"
                    checked={peopleHidden}
                    onCheckedChange={setPeopleHidden}
                  />
                  <label htmlFor="picture-people" className="font-medium text-sm">
                    {t("picture.people")}
                  </label>
                </div>
                <p className="hidden text-muted-foreground text-xs md:block">
                  {peopleHidden ? t("picture.peopleHidden") : t("picture.peopleShown")}
                </p>
              </div>
            ) : (
              <p className="border-t pt-3 text-muted-foreground text-xs">{t("picture.fileNote")}</p>
            )}
            {marks.length > 0 ? (
              <div className="hidden gap-2 border-t pt-3 md:grid">
                <h3 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
                  {t("picture.marks")}
                </h3>
                <ol className="grid gap-1.5 text-sm">
                  {marks.map((mark, index) => (
                    // biome-ignore lint/suspicious/noArrayIndexKey: marks are numbered by their place
                    <li key={index} className="flex items-center gap-2">
                      <span
                        className="grid size-5 shrink-0 place-items-center rounded-full font-bold text-[11px] text-white"
                        style={{ background: MARK }}
                      >
                        {index + 1}
                      </span>
                      <span className="first-letter:uppercase">
                        {mark.part ? partName(mark.part) : t("picture.area")}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {page ? (
              <p className="hidden text-muted-foreground text-xs md:block">{t("picture.keys")}</p>
            ) : null}
            {failed ? (
              <p className="text-destructive text-xs" role="alert">
                {failed}
              </p>
            ) : null}
          </div>
        </div>
        {/* Cancel closes the dialog, which puts the picture back as it was left. */}
        <DialogFooter
          className="items-center border-t px-4 py-3"
          submitLabel={attached ? t("common:done") : t("picture.attach")}
          onSubmit={save}
          pending={saving}
          disabled={!size}
        >
          <span className="min-w-0 flex-1 text-muted-foreground text-xs">{t("picture.who")}</span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

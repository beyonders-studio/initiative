/**
 * Collaboration, drawn: three people on the same plan at once. Maya types a
 * line and her caret follows it (a typewriter, so the line wraps as the
 * finished text would in any language), Dev selects a word and his caret sits at
 * its end, Priya's comment lands in the margin and picks up a reaction, and
 * a task on the page is handed to a second person. The avatar stack in the
 * header fills as they arrive.
 *
 * It plays once, when it is scrolled into view, and ends on the finished
 * picture. Every animated piece is styled as that finished picture, with
 * the keyframes starting from the empty state, so with less motion asked
 * for the drawing simply stands finished. It is a picture, not a working
 * screen: one image to a screen reader.
 */

import { AtSign, Check, MessageSquareText, Share2, ThumbsUp, Users } from "lucide-react";
import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/ui/lib/utils";

import { reveal, Typed, useRevealOnScroll } from "./effects";

const PEOPLE = {
  MA: { color: "#be185d" },
  DV: { color: "#0e7490" },
  PR: { color: "#b91c1c" },
  HA: { color: "#6d28d9" },
} as const;

type Initials = keyof typeof PEOPLE;

const Avatar = ({ who, className, style, ...rest }: { who: Initials } & ComponentProps<"span">) => (
  <span
    className={cn(
      "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 border-card font-bold text-3xs text-white",
      className
    )}
    style={{ backgroundColor: PEOPLE[who].color, ...style }}
    {...rest}
  >
    {who}
  </span>
);

/** Somebody else's caret: a bar in their colour with their name on a flag. */
const Caret = ({ who, name, className }: { who: Initials; name: string; className?: string }) => (
  <span
    className={cn("relative inline-block h-[1.15em] w-0.5 align-text-bottom", className)}
    style={{ backgroundColor: PEOPLE[who].color, animation: "liveBlink 1.1s steps(2) infinite" }}
    data-live
  >
    <span
      className="absolute -top-4 left-0 whitespace-nowrap rounded-sm rounded-bl-none px-1 font-semibold text-2xs text-white leading-4"
      style={{ backgroundColor: PEOPLE[who].color }}
    >
      {name}
    </span>
  </span>
);

const POINTS = [
  { icon: Users, title: "together.points.sameTitle", body: "together.points.sameBody" },
  { icon: Share2, title: "together.points.shareTitle", body: "together.points.shareBody" },
  { icon: AtSign, title: "together.points.handTitle", body: "together.points.handBody" },
] as const;

const Drawing = ({ playing }: { playing: boolean }) => {
  const { t } = useTranslation("landing");
  const p = (key: string) => t(`together.people.${key}` as never) as string;

  return (
    <div
      role="img"
      aria-label={t("together.drawingAria")}
      className={cn(
        "landing-live grid overflow-hidden rounded-3xl border bg-card text-card-foreground shadow-2xl md:grid-cols-[minmax(0,1fr)_17rem]",
        playing && "landing-live--on"
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-3 border-b px-4 py-3 sm:px-6">
          <div className="min-w-0 flex-1">
            <p className="truncate font-extrabold">{t("together.doc.title")}</p>
            <p className="flex items-center gap-1.5 text-muted-foreground text-xs">
              <Share2 className="h-3 w-3" aria-hidden="true" />
              {t("together.doc.sharedWith")}
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-green-100 px-2.5 py-0.5 font-semibold text-green-800 text-xs dark:bg-green-900/40 dark:text-green-200">
            <i className="h-2 w-2 rounded-full bg-green-500" />
            {t("together.doc.live")}
          </span>
          <span className="flex -space-x-2">
            <Avatar who="MA" />
            <Avatar
              who="DV"
              data-live
              style={{
                animation: "livePop 0.5s cubic-bezier(.2,1.4,.4,1) 0.6s both",
              }}
            />
            <Avatar
              who="PR"
              data-live
              style={{
                animation: "livePop 0.5s cubic-bezier(.2,1.4,.4,1) 2.4s both",
              }}
            />
          </span>
        </div>

        <div className="flex flex-col gap-3.5 px-4 py-5 text-[15px] leading-relaxed sm:px-6 sm:text-base">
          <p className="font-bold text-lg sm:text-xl">{t("together.doc.heading")}</p>
          <p className="text-muted-foreground">{t("together.doc.line1")}</p>
          <p>
            {t("together.doc.line2Start")}{" "}
            <span
              className="rounded-sm px-0.5"
              style={{ backgroundColor: `${PEOPLE.DV.color}33` }}
              data-live
            >
              <span
                className="inline-block overflow-hidden whitespace-nowrap align-bottom"
                style={{ animation: "liveWidth 0.7s steps(8, end) 1.8s both" }}
                data-live
              >
                {t("together.doc.line2Selected")}
              </span>
            </span>
            <Caret who="DV" name={p("dev")} className="ml-px" />
            {t("together.doc.line2End")}
          </p>
          <ul className="flex flex-col gap-1.5">
            <li className="flex items-center gap-2.5">
              <span className="flex h-4.5 w-4.5 shrink-0 items-center justify-center rounded-[5px] bg-primary text-primary-foreground">
                <Check className="h-3 w-3" aria-hidden="true" />
              </span>
              <span className="text-muted-foreground">{t("together.doc.task1")}</span>
            </li>
            <li className="flex items-center gap-2.5">
              <span className="h-4.5 w-4.5 shrink-0 rounded-[5px] border-2 border-muted-foreground/50" />
              <span className="min-w-0 flex-1">{t("together.doc.task2")}</span>
              <span className="flex -space-x-1.5">
                <Avatar who="DV" className="h-6 w-6" />
                <Avatar
                  who="HA"
                  className="h-6 w-6"
                  data-live
                  style={{
                    animation: "liveSlideIn 0.5s cubic-bezier(.2,1.2,.4,1) 3.6s both",
                  }}
                />
              </span>
            </li>
          </ul>
          <p>
            <Typed
              text={t("together.doc.typed")}
              play={playing}
              delayMs={300}
              caret={<Caret who="MA" name={p("maya")} className="ml-px" />}
            />
          </p>
        </div>
      </div>

      <aside className="flex flex-col gap-3 border-t bg-muted/50 p-4 md:border-t-0 md:border-l">
        <p className="flex items-center gap-1.5 font-bold text-muted-foreground text-xs uppercase">
          <MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" />
          {t("together.comments.title")}
        </p>
        <div
          className="rounded-xl border bg-card p-3 text-sm shadow-sm"
          style={{ animation: "liveIn 0.6s ease-out 2.6s both" }}
          data-live
        >
          <div className="flex items-center gap-2">
            <Avatar who="PR" className="h-6 w-6" />
            <b>{p("priya")}</b>
            <span className="ml-auto text-muted-foreground text-xs">
              {t("together.comments.justNow")}
            </span>
          </div>
          <p className="mt-1.5">
            <span className="rounded bg-primary/15 px-1 font-semibold text-primary">
              {t("together.comments.mention")}
            </span>{" "}
            {t("together.comments.text")}
          </p>
          <div className="mt-2 flex gap-1.5 text-xs">
            <span
              className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-semibold"
              style={{ animation: "livePop 0.4s cubic-bezier(.2,1.4,.4,1) 4.4s both" }}
              data-live
            >
              <ThumbsUp className="h-3 w-3" aria-hidden="true" /> 2
            </span>
          </div>
        </div>
        <div
          className="rounded-xl border bg-card p-3 text-sm shadow-sm"
          style={{ animation: "liveIn 0.6s ease-out 4.2s both" }}
          data-live
        >
          <div className="flex items-center gap-2">
            <Avatar who="HA" className="h-6 w-6" />
            <b>{p("hana")}</b>
            <span className="ml-auto text-muted-foreground text-xs">
              {t("together.comments.justNow")}
            </span>
          </div>
          <p className="mt-1.5">{t("together.comments.reply")}</p>
        </div>
      </aside>
    </div>
  );
};

export const Together = () => {
  const { t } = useTranslation("landing");
  const { ref, isVisible } = useRevealOnScroll<HTMLDivElement>(0.3);

  return (
    <section className="bg-muted/40" aria-labelledby="landing-together-title">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-22">
        <div className="mb-8 max-w-3xl">
          <h2
            id="landing-together-title"
            className="font-extrabold text-3xl tracking-tight sm:text-5xl"
          >
            {t("together.titleStart")}{" "}
            <span className="text-primary">{t("together.titleHighlight")}</span>
          </h2>
          <p className="mt-4 text-lg text-muted-foreground">{t("together.description")}</p>
        </div>
        <div
          ref={ref}
          className={cn(
            "transition-[transform,opacity] duration-700 motion-reduce:transition-none",
            reveal(isVisible)
          )}
        >
          <Drawing playing={isVisible} />
        </div>
        <ul className="mt-12 hidden gap-7 md:grid md:grid-cols-3">
          {POINTS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex flex-col gap-2">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/30">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <h3 className="mt-1 font-bold text-xl">{t(title)}</h3>
              <p className="text-muted-foreground">{t(body)}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};

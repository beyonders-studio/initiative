/**
 * The social side: a drawing of one community on an ordinary week (a pinned
 * post with a poll, Saturday's game and who's coming, whose turn it is, who's
 * around), then the community directory for somebody looking for a new
 * group to join.
 *
 * The drawing is a picture, not a working screen, so it is one image to a
 * screen reader. The directory part only appears on a deployment that runs a
 * directory, and its category chips are the one thing here that does
 * something: each brings that category's community to the front of the deck.
 */

import { Link } from "@tanstack/react-router";
import { Bell, CalendarDays, Check, Heart, Megaphone, ThumbsUp, Users } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { cn } from "@/ui/lib/utils";

import { DarkBand } from "./DarkBand";
import { useFrontDoor } from "./useFrontDoor";

const AVATAR_COLORS = {
  MA: "#be185d",
  DV: "#0e7490",
  PR: "#b91c1c",
  LU: "#4d7c0f",
  SM: "#0f766e",
  HA: "#6d28d9",
} as const;

type Initials = keyof typeof AVATAR_COLORS;

const Avatar = ({ who, className }: { who: Initials; className?: string }) => (
  <span
    className={cn(
      "inline-flex h-6.5 w-6.5 shrink-0 items-center justify-center rounded-full font-bold text-3xs text-white",
      className
    )}
    style={{ backgroundColor: AVATAR_COLORS[who] }}
  >
    {who}
  </span>
);

const PRESENCE = { online: "bg-green-500", idle: "bg-amber-500", busy: "bg-red-500" } as const;

const Person = ({
  who,
  name,
  status,
  presence,
}: {
  who: Initials;
  name: string;
  status?: string;
  presence: keyof typeof PRESENCE;
}) => (
  <li className="flex items-center gap-2.5 font-medium text-sm">
    <span className="relative">
      <Avatar who={who} />
      <i
        className={cn(
          "absolute -right-0.5 -bottom-0.5 h-2.75 w-2.75 rounded-full border-2 border-muted",
          PRESENCE[presence]
        )}
      />
    </span>
    <span className="leading-tight">
      {name}
      {status ? (
        <small className="block font-normal text-muted-foreground text-xs">{status}</small>
      ) : null}
    </span>
  </li>
);

const PollOption = ({ label, share, mine }: { label: string; share: number; mine?: boolean }) => (
  <div className="relative flex justify-between overflow-hidden rounded-lg bg-muted px-2.5 py-1.5 text-sm">
    <span
      className={cn("absolute inset-y-0 left-0", mine ? "bg-primary/25" : "bg-primary/12")}
      style={{ width: `${share}%` }}
    />
    <span className={cn("relative", mine && "font-semibold")}>{label}</span>
    <span className={cn("relative", mine && "font-semibold")}>{share}%</span>
  </div>
);

const CommunityDrawing = () => {
  const { t } = useTranslation("landing");
  const p = (key: string) => t(`hangout.people.${key}` as never) as string;

  return (
    <div
      role="img"
      aria-label={t("hangout.drawingAria")}
      className="overflow-hidden rounded-3xl bg-card text-card-foreground shadow-2xl"
    >
      <div className="flex items-center gap-3 border-b px-4 py-3.5">
        <span className="flex h-9.5 w-9.5 items-center justify-center rounded-full bg-green-700 font-bold text-sm text-white">
          ER
        </span>
        <div className="min-w-0">
          <p className="font-extrabold">{t("hangout.community.name")}</p>
          <p className="hidden text-muted-foreground text-xs sm:block">
            {t("hangout.community.tagline")}
          </p>
        </div>
        <span className="ml-auto inline-flex items-center gap-1.5 whitespace-nowrap font-semibold text-green-700 text-sm dark:text-green-400">
          <i className="h-2 w-2 rounded-full bg-green-500" />
          {t("hangout.community.online")}
        </span>
      </div>
      <div className="grid bg-muted/40 md:grid-cols-[12rem_minmax(0,1fr)_minmax(0,18rem)]">
        <div className="hidden flex-col gap-2 p-4 md:flex">
          <p className="font-bold text-muted-foreground text-xs uppercase">{t("hangout.online")}</p>
          <ul className="flex flex-col gap-2">
            <Person who="MA" name={p("maya")} status={p("mayaStatus")} presence="online" />
            <Person who="DV" name={p("dev")} status={p("devStatus")} presence="online" />
            <Person who="PR" name={p("priya")} status={p("priyaStatus")} presence="busy" />
            <Person who="LU" name={p("luis")} presence="online" />
          </ul>
          <p className="mt-2 font-bold text-muted-foreground text-xs uppercase">
            {t("hangout.away")}
          </p>
          <ul className="flex flex-col gap-2">
            <Person who="SM" name={p("sam")} presence="idle" />
            <Person who="HA" name={p("hana")} presence="idle" />
          </ul>
        </div>
        <div className="flex flex-col gap-3 p-4 md:border-l">
          <div className="rounded-2xl border bg-card p-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs">
              <Avatar who="MA" />
              <b className="text-foreground text-sm">{p("maya")}</b>
              <span>{t("hangout.post.where")}</span>
              <span className="ml-auto inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-amber-100 px-2 py-0.5 font-bold text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                <Megaphone className="h-3 w-3" />
                {t("hangout.post.pinned")}
              </span>
            </div>
            <p className="mt-2">{t("hangout.post.body")}</p>
            <div className="mt-3 flex flex-col gap-1.5">
              <PollOption label={t("hangout.post.burgers")} share={62} mine />
              <PollOption label={t("hangout.post.hotDogs")} share={24} />
              <PollOption label={t("hangout.post.veggie")} share={14} />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-muted-foreground text-xs">
              <span className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-semibold text-foreground">
                <ThumbsUp className="h-3 w-3" /> 18
              </span>
              <span className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-semibold text-foreground">
                <Heart className="h-3 w-3" /> 9
              </span>
              <span>{t("hangout.post.votes")}</span>
              <span className="ml-auto">{t("hangout.post.read")}</span>
            </div>
          </div>
          <div className="hidden items-start gap-2.5 text-sm md:flex">
            <Avatar who="DV" />
            <p className="rounded-xl border bg-card px-3 py-2">
              <b>{p("dev")}</b> {t("hangout.reply")}
            </p>
          </div>
        </div>
        <div className="flex flex-col gap-3 border-t p-4 md:border-t-0 md:border-l">
          <div className="overflow-hidden rounded-2xl border bg-card">
            <div className="flex gap-3 p-3.5">
              <span className="flex h-14 w-13 shrink-0 flex-col items-center justify-center rounded-xl bg-[#0b1224] text-white leading-none">
                <small className="font-bold text-2xs text-amber-400 uppercase">
                  {t("hangout.event.day")}
                </small>
                <b className="text-2xl">{t("hangout.event.date")}</b>
              </span>
              <div>
                <p className="font-bold">{t("hangout.event.title")}</p>
                <p className="text-muted-foreground text-xs">{t("hangout.event.where")}</p>
              </div>
            </div>
            <div className="flex items-center gap-2.5 px-3.5 pb-3 text-sm">
              <span className="flex">
                {(["MA", "DV", "LU", "HA"] as const).map((who, i) => (
                  <Avatar
                    key={who}
                    who={who}
                    className={cn("h-6 w-6 border-2 border-card", i > 0 && "-ml-1.5")}
                  />
                ))}
              </span>
              <span>
                <b>{t("hangout.event.going")}</b>, {t("hangout.event.maybe")}
              </span>
            </div>
            <div className="grid grid-cols-3 gap-1.5 px-3.5 pb-3.5 font-semibold text-xs">
              <span className="flex min-h-9 items-center justify-center gap-1 rounded-lg bg-primary text-primary-foreground">
                <Check className="h-3.5 w-3.5" />
                {t("hangout.event.rsvpGoing")}
              </span>
              <span className="flex min-h-9 items-center justify-center rounded-lg border">
                {t("hangout.event.rsvpMaybe")}
              </span>
              <span className="flex min-h-9 items-center justify-center rounded-lg border">
                {t("hangout.event.rsvpNo")}
              </span>
            </div>
            <p className="flex items-center gap-2 border-t bg-muted/50 px-3.5 py-2.5 text-muted-foreground text-xs">
              <Bell className="h-3.5 w-3.5" />
              {t("hangout.event.reminder")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

const POINTS = [
  { icon: CalendarDays, title: "hangout.points.planTitle", body: "hangout.points.planBody" },
  { icon: Megaphone, title: "hangout.points.loopTitle", body: "hangout.points.loopBody" },
  { icon: Users, title: "hangout.points.aroundTitle", body: "hangout.points.aroundBody" },
] as const;

// --------------------------------------------------------------------------
// The directory deck
// --------------------------------------------------------------------------

const DECK = [
  { key: "dice", art: "ttrpg-dicetower", initials: "DD", color: "#7c3aed", second: false },
  { key: "producers", art: "music-festival", initials: "BP", color: "#db2777", second: true },
  { key: "volleyball", art: "volleyball-beach", initials: "SV", color: "#0891b2", second: true },
] as const;

type DeckKey = (typeof DECK)[number]["key"];

/** Where a card sits relative to the one in front. */
const SLOT = {
  front: "z-30 translate-x-0 rotate-0",
  right:
    "z-20 translate-x-[42px] translate-y-6 rotate-[5deg] scale-[.92] opacity-90 md:translate-x-[120px] md:rotate-[6deg]",
  left: "z-10 -translate-x-[42px] translate-y-6 -rotate-[5deg] scale-[.92] opacity-90 md:-translate-x-[120px] md:-rotate-[6deg]",
} as const;

const slotOf = (key: DeckKey, front: DeckKey) => {
  const keys = DECK.map((card) => card.key);
  const offset = (keys.indexOf(key) - keys.indexOf(front) + keys.length) % keys.length;
  return offset === 0 ? "front" : offset === 1 ? "right" : "left";
};

const Directory = () => {
  const { t } = useTranslation("landing");
  const { registrationOpen } = useFrontDoor();
  const [front, setFront] = useState<DeckKey>("volleyball");
  const d = (key: string) => t(`directory.${key}` as never) as string;

  return (
    <div className="mt-16 grid items-center gap-2 border-white/10 border-t pt-12 sm:mt-20 sm:pt-14 md:grid-cols-[5fr_6fr] md:gap-14">
      <div>
        <h2 className="font-extrabold text-3xl tracking-tight sm:text-4xl">
          {t("directory.title")}
        </h2>
        <p className="mt-3 text-slate-300">{t("directory.description")}</p>
        <div className="mt-6 rounded-2xl border border-white/12 bg-white/6 p-3.5">
          <fieldset className="flex flex-wrap gap-2">
            <legend className="mb-2 font-semibold text-slate-300 text-xs">
              {t("directory.peek")}
            </legend>
            {DECK.map((card) => (
              <button
                key={card.key}
                type="button"
                aria-pressed={front === card.key}
                onClick={() => setFront(card.key)}
                className={cn(
                  "min-h-10 rounded-full border px-3.5 font-semibold text-sm focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2",
                  front === card.key
                    ? "border-amber-400 bg-amber-400 text-amber-950"
                    : "border-white/25 text-slate-200 hover:bg-white/8"
                )}
              >
                {d(`${card.key}.category`)}
              </button>
            ))}
          </fieldset>
          <Button className="mt-3.5 w-full bg-white text-slate-950 hover:bg-slate-100" asChild>
            {registrationOpen ? (
              <Link to="/start">{t("directory.signUp")}</Link>
            ) : (
              <Link to="/login" search={true}>
                {t("directory.signIn")}
              </Link>
            )}
          </Button>
        </div>
        <p className="mt-3 text-slate-400 text-sm">{t("directory.age")}</p>
      </div>
      <ul className="relative -mx-4 h-96 md:mx-0 md:h-105" aria-label={t("directory.deckAria")}>
        {DECK.map((card) => (
          <li
            key={card.key}
            aria-hidden={front === card.key ? undefined : "true"}
            className={cn(
              "absolute top-6 left-1/2 -ml-[135px] flex w-[270px] flex-col overflow-hidden rounded-2xl border bg-card text-card-foreground shadow-2xl transition-[transform,opacity] duration-500 motion-reduce:transition-none md:-ml-[165px] md:w-[330px]",
              SLOT[slotOf(card.key, front)]
            )}
          >
            <img
              src={`/decorations/banners/${card.art}.svg`}
              alt=""
              className="aspect-[4/1] w-full object-cover"
            />
            <div className="flex flex-col gap-3 p-4">
              <div className="flex items-start gap-3">
                <span
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-bold text-sm text-white"
                  style={{ backgroundColor: card.color }}
                >
                  {card.initials}
                </span>
                <div className="min-w-0">
                  <h3 className="truncate font-semibold">{d(`${card.key}.name`)}</h3>
                  <p className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground text-xs">
                    <span className="flex items-center gap-1 font-medium text-emerald-700 dark:text-emerald-400">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      {d(`${card.key}.online`)}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span className="flex items-center gap-1">
                      <Users className="h-3 w-3" aria-hidden="true" />
                      {d(`${card.key}.members`)}
                    </span>
                  </p>
                </div>
              </div>
              <p className="text-muted-foreground text-sm">{d(`${card.key}.description`)}</p>
              <div className="flex flex-wrap gap-1.5">
                <span className="rounded-md bg-secondary px-2 py-0.5 text-xs">
                  {d(`${card.key}.category`)}
                </span>
                {card.second ? (
                  <span className="rounded-md bg-secondary px-2 py-0.5 text-xs">
                    {d(`${card.key}.category2`)}
                  </span>
                ) : null}
              </div>
              <span className="flex h-9 items-center justify-center rounded-md bg-primary font-medium text-primary-foreground text-sm">
                {t("directory.join")}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

export const HangOut = () => {
  const { t } = useTranslation("landing");
  const { communityDirectoryEnabled } = useFrontDoor();

  return (
    <DarkBand stars aria-labelledby="landing-hangout-title">
      <div className="relative mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-22">
        <div className="mb-8 max-w-3xl">
          <h2
            id="landing-hangout-title"
            className="font-extrabold text-3xl tracking-tight sm:text-5xl"
          >
            {t("hangout.titleStart")}{" "}
            <span className="text-amber-400">{t("hangout.titleHighlight")}</span>
            {t("hangout.titleEnd")}
          </h2>
          <p className="mt-4 text-lg text-slate-300">{t("hangout.description")}</p>
        </div>
        <CommunityDrawing />
        <ul className="mt-12 hidden gap-7 md:grid md:grid-cols-3">
          {POINTS.map(({ icon: Icon, title, body }) => (
            <li key={title} className="flex flex-col gap-2">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-400/15 text-amber-400 ring-1 ring-amber-400/40">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <h3 className="mt-1 font-bold text-xl">{t(title)}</h3>
              <p className="text-slate-300">{t(body)}</p>
            </li>
          ))}
        </ul>
        {communityDirectoryEnabled ? <Directory /> : null}
      </div>
    </DarkBand>
  );
};

/**
 * The front door, for somebody who is not signed in.
 *
 * It leads with signing up and what a community looks like once it's here,
 * then what's inside: the tools (drawn by the same sketches the create wizard
 * uses, so a new tool shows up here without anybody remembering to add it),
 * people working on the same page at once, the community side of things, and
 * the features every tool shares. Plans
 * and the free trial appear only where this deployment sells them.
 *
 * Kept short on purpose, phones most of all: a phone gets the hero and the
 * marquee but not the big community cards, and the wider sections fold into
 * rows that scroll sideways.
 */

import { Link, useRouter } from "@tanstack/react-router";
import type { ParseKeys } from "i18next";
import { BookOpen, Download, Gift, Pause, Play, Server, Trash2, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Tool } from "@/api/generated/initiativeAPI.schemas";
import { LogoIcon } from "@/components/icons/LogoIcon";
import { ToolIconTile, ToolSketch } from "@/components/initiatives/ToolSkeletons";
import { useAuth } from "@/hooks/useAuth";
import { DOCS_URL, docsUrl } from "@/lib/links";
import { TOOL_ICONS, TOOLS, toolCamelPlural, toolNavLabelKey } from "@/lib/tools";
import { DarkBand } from "@/pages/site/DarkBand";
import { FloatingShape } from "@/pages/site/effects";
import { SiteShell } from "@/pages/site/SiteShell";
import { useFrontDoor } from "@/pages/site/useFrontDoor";
import { usePageMeta } from "@/pages/site/usePageMeta";
import { Button } from "@/ui/button";

import { BitsBetween } from "./BitsBetween";
import { HangOut } from "./HangOut";
import { Together } from "./Together";

/** A photo cropped to banner shape for one of the example communities. */
const photo = (name: string) => `/homepage/${name}.webp`;

interface ExampleCommunity {
  key: "dnd" | "band" | "pta";
  art: string;
  initials: string;
  color: string;
  members: number;
  /** The tools it uses, and the one its latest activity came from. */
  tools: Tool[];
  activity: Tool;
  centered?: boolean;
}

const HERO_COMMUNITIES: ExampleCommunity[] = [
  {
    key: "dnd",
    art: photo("fantasy-map"),
    initials: "TD",
    color: "#7c3aed",
    members: 6,
    tools: [Tool.calendar, Tool.wiki, Tool.counter_group],
    activity: Tool.calendar,
    centered: true,
  },
  {
    key: "band",
    art: photo("instruments"),
    initials: "TB",
    color: "#0f766e",
    members: 4,
    tools: [Tool.calendar, Tool.project, Tool.file],
    activity: Tool.calendar,
  },
  {
    key: "pta",
    art: photo("classroom"),
    initials: "HP",
    color: "#dc2626",
    members: 38,
    tools: [Tool.counter_group, Tool.post, Tool.project],
    activity: Tool.counter_group,
  },
];

const MARQUEE = [
  ["soccer", "street"],
  ["pta", "campus"],
  ["business", "bakery"],
  ["books", "book-pages"],
  ["breakfast", "breakfast-club"],
  ["neighborhood", "meetup"],
  ["theater", "theater"],
  ["faith", "food-bank"],
  ["robotics", "robot"],
  ["family", "family"],
] as const;

const CommunityCard = ({ community, big }: { community: ExampleCommunity; big: boolean }) => {
  const { t } = useTranslation("landing");
  const ActivityIcon = TOOL_ICONS[community.activity];
  return (
    <article
      className={`landing-float overflow-hidden rounded-2xl bg-card text-card-foreground shadow-2xl ${big ? "col-span-2" : ""}`}
      style={{ animation: `cardFloat ${big ? 7 : 8}s ease-in-out ${big ? 0 : -3}s infinite` }}
    >
      <div className={`relative flex items-center overflow-hidden px-4 ${big ? "h-32" : "h-24"}`}>
        <img src={community.art} alt="" className="absolute inset-0 h-full w-full object-cover" />
        <span className="absolute inset-0 bg-gradient-to-t from-black/55 to-black/10" />
        <p
          className={`relative w-full font-extrabold text-white text-xl drop-shadow ${community.centered ? "text-center" : ""}`}
        >
          {t(`communities.${community.key}.name`)}
        </p>
      </div>
      <div className="relative px-4 pt-3 pb-4">
        <span
          className="absolute -top-5 left-3.5 flex h-10 w-10 items-center justify-center rounded-full border-3 border-card font-bold text-sm text-white"
          style={{ backgroundColor: community.color }}
          aria-hidden="true"
        >
          {community.initials}
        </span>
        <p className="ml-14 text-muted-foreground text-xs">
          {t("communities.members", { count: community.members })}
        </p>
        <ul
          className="mt-3 flex gap-1.5 text-muted-foreground"
          aria-label={t("communities.toolsAria")}
        >
          {community.tools.map((tool) => {
            const Icon = TOOL_ICONS[tool];
            return (
              <li
                key={tool}
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-muted"
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
              </li>
            );
          })}
        </ul>
        <p className="mt-3 flex items-center gap-2.5 rounded-xl bg-primary/10 px-3 py-2.5 font-medium text-sm">
          <ActivityIcon className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>{t(`communities.${community.key}.activity`)}</span>
          {community.key === "dnd" ? (
            <span className="ml-auto whitespace-nowrap rounded-full bg-primary px-2 py-0.5 font-bold text-2xs text-primary-foreground">
              {t("communities.dnd.pill")}
            </span>
          ) : null}
        </p>
      </div>
    </article>
  );
};

/** The communities scrolling past. It can be paused, as anything that moves
 *  on its own must be; with reduced motion asked for it holds still and
 *  wraps instead. */
const Marquee = () => {
  const { t } = useTranslation("landing");
  const [paused, setPaused] = useState(false);
  return (
    <div className="relative mx-auto max-w-6xl px-4 pb-14 sm:px-8 sm:pb-18">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="font-semibold text-slate-300 text-sm">{t("communities.alsoGoodFor")}</h2>
        <button
          type="button"
          onClick={() => setPaused((value) => !value)}
          aria-pressed={paused}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-white/20 px-3 font-semibold text-slate-200 text-xs hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 motion-reduce:hidden"
        >
          {paused ? (
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Pause className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {paused ? t("communities.play") : t("communities.pause")}
        </button>
      </div>
      <div
        className="-mx-4 overflow-hidden motion-reduce:mx-0 md:mx-0 motion-reduce:[mask-image:none]"
        style={{
          maskImage: "linear-gradient(90deg, transparent, black 8%, black 92%, transparent)",
          WebkitMaskImage: "linear-gradient(90deg, transparent, black 8%, black 92%, transparent)",
        }}
      >
        <div
          className={`landing-ribbon__track flex w-max animate-[ribbonScroll_45s_linear_infinite] motion-reduce:w-auto hover:[animation-play-state:paused] ${paused ? "[animation-play-state:paused]" : ""}`}
        >
          {[0, 1].map((copy) => (
            <ul
              key={copy}
              className={`flex shrink-0 gap-2.5 pr-2.5 motion-reduce:flex-wrap motion-reduce:pr-0 sm:gap-3.5 sm:pr-3.5 ${copy === 1 ? "motion-reduce:hidden" : ""}`}
              aria-hidden={copy === 1 ? "true" : undefined}
            >
              {MARQUEE.map(([key, art]) => (
                <li
                  key={key}
                  className="relative flex h-21 w-48 shrink-0 items-end overflow-hidden rounded-xl p-3 md:h-23 md:w-60"
                >
                  <img
                    src={photo(art)}
                    alt=""
                    className="absolute inset-0 h-full w-full object-cover"
                  />
                  <span className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-black/65 to-transparent" />
                  <span className="relative font-extrabold text-white leading-tight sm:text-lg">
                    {t(`communities.marquee.${key}`)}
                  </span>
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>
    </div>
  );
};

const Hero = () => {
  const { t } = useTranslation("landing");
  const { registrationOpen, sellsPlans } = useFrontDoor();
  const [scrollY, setScrollY] = useState(0);

  useEffect(() => {
    const onScroll = () => setScrollY(window.scrollY);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <DarkBand stars aria-labelledby="landing-hero-title">
      <FloatingShape
        className="top-[12%] left-[3%] hidden md:block"
        parallaxOffset={-scrollY * 0.12}
        shape="hexagon"
        size={78}
        isDark
      />
      <FloatingShape
        className="top-[5%] left-[45%] hidden md:block"
        parallaxOffset={-scrollY * 0.05}
        shape="ring"
        size={64}
        isDark
      />
      <FloatingShape
        className="top-[78%] left-[2%] hidden md:block"
        parallaxOffset={-scrollY * 0.05}
        shape="diamond"
        size={40}
        isDark
      />
      <FloatingShape
        className="top-[82%] right-[4%] hidden md:block"
        parallaxOffset={-scrollY * 0.2}
        shape="ring"
        size={96}
        isDark
      />
      <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 pt-10 pb-10 sm:px-8 sm:pt-20 md:grid-cols-[11fr_10fr] md:gap-14">
        <div>
          <h1
            id="landing-hero-title"
            className="font-extrabold text-[2.75rem] leading-[1.02] tracking-tight sm:text-6xl"
            aria-label={t("hero.titleAria")}
          >
            <span className="block text-4xl">{t("hero.titleLine1")}</span>
            <span className="relative block w-fit text-amber-400 sm:text-[2.5rem]">
              {t("hero.titleLine2")}
              <span
                className="absolute bottom-0 left-0 h-1.5 rounded-full bg-amber-400/35"
                style={{ animation: "heroLine 1.2s ease-out 1s forwards", width: 0 }}
                aria-hidden="true"
              />
            </span>
          </h1>
          <p className="mt-5 text-lg text-slate-300 sm:text-xl">{t("hero.subtitle")}</p>
          {sellsPlans ? (
            <div className="mt-7 flex items-start gap-4 rounded-2xl border border-amber-400/35 bg-amber-400/10 p-4 sm:p-5">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-amber-400 text-amber-950">
                <Gift className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="font-bold text-lg">{t("hero.freeTitle")}</h2>
                <p className="mt-1 text-slate-200">{t("hero.freeBody")}</p>
              </div>
            </div>
          ) : null}
          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <Button
              size="lg"
              className="h-14 bg-white px-7 text-base text-slate-950 hover:bg-slate-100"
              asChild
            >
              {registrationOpen ? (
                <Link to="/start">{t("hero.signUp")}</Link>
              ) : (
                <Link to="/login" search={true}>
                  {t("hero.signIn")}
                </Link>
              )}
            </Button>
            <Button
              size="lg"
              variant="outline"
              className="h-14 border-white/30 bg-white/5 px-7 text-base text-white hover:bg-white/10 hover:text-white"
              asChild
            >
              <Link to="/download">
                <Download className="h-5 w-5" aria-hidden="true" />
                {t("hero.download")}
              </Link>
            </Button>
          </div>
          {registrationOpen ? (
            <p className="mt-4 text-slate-300 text-sm">
              {t("hero.haveAccount")}{" "}
              <Link
                to="/login"
                search={true}
                className="font-semibold text-sky-300 hover:underline"
              >
                {t("hero.signIn")}
              </Link>
            </p>
          ) : null}
        </div>
        {/* The big cards are for wide screens only: on a phone the marquee
            under the hero says the same thing in a fraction of the space. */}
        <div className="hidden grid-cols-2 gap-4 md:grid">
          {HERO_COMMUNITIES.map((community, i) => (
            <CommunityCard key={community.key} community={community} big={i === 0} />
          ))}
        </div>
      </div>
      <Marquee />
    </DarkBand>
  );
};

const Tools = () => {
  const { t } = useTranslation("landing");
  const { t: tNav } = useTranslation("nav");
  return (
    <section
      className="mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-22"
      aria-labelledby="landing-tools-title"
    >
      <div className="mb-7 sm:mx-auto sm:mb-12 sm:max-w-2xl sm:text-center">
        <h2 id="landing-tools-title" className="font-extrabold text-3xl tracking-tight sm:text-5xl">
          {t("tools.title")}
        </h2>
        <p className="mt-3 text-lg text-muted-foreground">{t("tools.description")}</p>
      </div>
      <ul className="grid grid-cols-3 gap-1.5 sm:gap-3">
        {TOOLS.map((tool) => (
          <li
            key={tool}
            className="flex flex-col gap-1.5 rounded-xl border bg-card p-1.5 sm:gap-2.5 sm:rounded-2xl sm:p-3.5"
            data-tool={tool}
          >
            <ToolSketch tool={tool} active />
            <div className="flex items-center gap-2.5 px-0.5">
              <span className="hidden md:block">
                <ToolIconTile tool={tool} active />
              </span>
              <h3 className="font-semibold text-[13px] sm:font-bold sm:text-lg">
                {tNav(toolNavLabelKey(tool))}
              </h3>
            </div>
            <p className="hidden text-muted-foreground text-sm md:block">
              {t(`tools.${toolCamelPlural(tool)}` as ParseKeys<"landing">)}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-5 text-muted-foreground sm:text-center">{t("tools.note")}</p>
    </section>
  );
};

const Safe = () => {
  const { t } = useTranslation("landing");
  return (
    <section className="bg-amber-50 dark:bg-amber-950/25" aria-labelledby="landing-safe-title">
      <div className="mx-auto grid max-w-6xl items-center gap-4 px-4 py-10 sm:px-8 sm:py-14 md:grid-cols-[1fr_26rem] md:gap-10">
        <div>
          <h2
            id="landing-safe-title"
            className="font-extrabold text-3xl tracking-tight sm:text-4xl"
          >
            {t("safe.title")}
          </h2>
          <p className="mt-2 text-lg text-stone-600 dark:text-stone-300">{t("safe.body")}</p>
        </div>
        <div
          className="flex items-center gap-3 rounded-xl bg-[#0b1224] px-4 py-3 text-slate-200 text-sm"
          aria-hidden="true"
        >
          <Trash2 className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1">
            {t("safe.item")}
            <span className="block text-slate-400 text-xs">{t("safe.deleted")}</span>
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-400 px-3 py-1.5 font-bold text-amber-950">
            <Undo2 className="h-3.5 w-3.5" />
            {t("safe.restore")}
          </span>
        </div>
      </div>
    </section>
  );
};

const Closer = () => {
  const { t } = useTranslation("landing");
  const { registrationOpen } = useFrontDoor();
  return (
    <DarkBand stars aria-labelledby="landing-closer-title">
      <div className="relative mx-auto max-w-6xl px-4 py-14 sm:px-8 sm:py-22 sm:text-center">
        <h2
          id="landing-closer-title"
          className="font-extrabold text-3xl tracking-tight sm:text-5xl"
        >
          {t("closer.title")}
        </h2>
        <p className="mt-3 text-lg text-slate-300 sm:mx-auto sm:max-w-xl">{t("closer.body")}</p>
        <div className="mt-7 flex flex-col gap-3 sm:flex-row md:justify-center">
          {registrationOpen ? (
            <Button
              size="lg"
              className="h-14 bg-amber-400 px-7 text-amber-950 text-base hover:bg-amber-300"
              asChild
            >
              <Link to="/start">{t("closer.start")}</Link>
            </Button>
          ) : null}
          <Button
            size="lg"
            variant="outline"
            className="h-14 border-white/30 bg-white/5 px-7 text-base text-white hover:bg-white/10 hover:text-white"
            asChild
          >
            <Link to="/download">
              <Download className="h-5 w-5" aria-hidden="true" />
              {t("hero.download")}
            </Link>
          </Button>
        </div>
        <p className="mt-6 flex flex-col gap-2.5 sm:flex-row sm:gap-7 md:justify-center">
          <a
            href={docsUrl("running-a-server/")}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 font-semibold text-sky-300 hover:underline"
          >
            <Server className="h-4 w-4" aria-hidden="true" />
            {t("closer.selfHost")}
          </a>
          <a
            href={DOCS_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 font-semibold text-sky-300 hover:underline"
          >
            <BookOpen className="h-4 w-4" aria-hidden="true" />
            {t("closer.docs")}
          </a>
        </p>
      </div>
    </DarkBand>
  );
};

export const WelcomePage = () => {
  const { t } = useTranslation("landing");
  const { token, loading } = useAuth();
  const router = useRouter();
  usePageMeta(t("meta.homeTitle"), t("meta.homeDescription"));

  // Somebody already signed in has no business on the front door.
  useEffect(() => {
    if (!loading && token) {
      router.navigate({ to: "/", replace: true });
    }
  }, [token, loading, router]);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <LogoIcon className="h-12 w-12 animate-pulse" />
          <p className="text-muted-foreground text-sm uppercase tracking-widest">
            {t("hero.loading")}
          </p>
        </div>
      </div>
    );
  }

  if (token) {
    return null;
  }

  return (
    <SiteShell>
      <Hero />
      <Tools />
      <Together />
      <HangOut />
      <BitsBetween />
      <Safe />
      <Closer />
    </SiteShell>
  );
};

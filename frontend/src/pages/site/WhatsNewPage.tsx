/**
 * What's new: the changelog, as posts.
 *
 * Each released version is one post, newest first, read from the changelog
 * the server ships with. The latest leads the list as a feature, with its
 * first picture as a cover, how much it added, changed and fixed, and its
 * first few changes; the rest show their first few headlines as a teaser. A
 * post gives each change its own headline under its section, the release's
 * first change set apart, and on Initiative Cloud the suggestions that
 * shipped in it. The unreleased section isn't a post, since nobody can have
 * it yet.
 */

import { Link, useParams } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";
import {
  Archive,
  ArrowLeft,
  ArrowRight,
  CircleCheck,
  Gift,
  Info,
  Megaphone,
  Minus,
  RefreshCw,
  ShieldCheck,
  ThumbsUp,
  TriangleAlert,
  Wrench,
} from "lucide-react";
import { type ReactNode, useContext, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ChangelogEntry, IdeaRead } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/markdown/Markdown";
import { useShippedIdeas } from "@/hooks/useIdeas";
import { useServer } from "@/hooks/useServer";
import { useChangelog } from "@/hooks/useSettings";
import { ThemeContext } from "@/hooks/useTheme";
import { isCloudOrigin } from "@/lib/cloud";
import { DOCS_URL, REPO_URL } from "@/lib/links";
import { RELEASE_IMAGE_DIR, releaseImageUrl } from "@/lib/releaseImages";
import { Button } from "@/ui/button";
import { dateTimeFormat } from "@/ui/lib/intl";
import { cn } from "@/ui/lib/utils";
import { ListSkeleton, SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { DarkBand } from "./DarkBand";
import { SiteShell } from "./SiteShell";
import { usePageMeta } from "./usePageMeta";

const PAGE_SIZE = 10;
const TEASER_HEADLINES = 3;
const FEATURE_HEADLINES = 4;

type Change = { headline: string; body: string; issues: string[] };
type ReleaseSection = { key: string; name: string; changes: Change[] };

/** Markdown read as plain text: pictures dropped, links as their words. */
const plainText = (markdown: string): string =>
  markdown
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[*`]/g, "")
    .trim();

/** A change's bullet, its indented lines brought back to the margin, split
 *  into its bold lead, which is how a release names a change, and the rest. */
const changeOf = (lines: string[]): Change => {
  const whole = lines.join("\n").trim();
  const issues = [...whole.matchAll(/\(#(\d+)\)/g)].map((match) => match[1]);
  const text = whole.replace(/[ \t]*\(#\d+\)/g, "");
  const lead = text.match(/^\*\*(.+?)\*\*[ \t]*/);
  return lead
    ? { headline: lead[1].replace(/[.:]$/, ""), body: text.slice(lead[0].length), issues }
    : { headline: "", body: text, issues };
};

/** A release's sections (Added, Changed, Fixed, …), each with its changes:
 *  one per top-level bullet. */
const sectionsOf = (changes: string): ReleaseSection[] =>
  changes
    .split(/^### /m)
    .slice(1)
    .map((section) => {
      const [name = "", ...lines] = section.split("\n");
      const bullets: string[][] = [];
      for (const line of lines) {
        if (line.startsWith("- ")) bullets.push([line.slice(2)]);
        else bullets.at(-1)?.push(line.replace(/^ {2}/, ""));
      }
      return {
        key: name.trim().toLowerCase().replace(/\s+/g, ""),
        name: name.trim(),
        changes: bullets.map(changeOf),
      };
    })
    .filter((section) => section.changes.length > 0);

/** Each named change, with its first line of detail as plain text. */
const changesOf = (changes: string) =>
  sectionsOf(changes)
    .flatMap((section) => section.changes)
    .filter((change) => change.headline)
    .map(({ headline, body }) => ({ headline, detail: plainText(body.split("\n")[0]) }));

const headlines = (changes: string): string[] => changesOf(changes).map((c) => c.headline);

const TALLIED = ["added", "changed", "fixed"] as const;

/** How many changes a release lists under Added, Changed and Fixed. */
const tallyOf = (changes: string) =>
  sectionsOf(changes).flatMap((section) => {
    const key = TALLIED.find((tallied) => tallied === section.key);
    return key ? [{ key, count: section.changes.length }] : [];
  });

/** A release's first picture, to stand as its feature's cover. */
const coverOf = (changes: string) => {
  const match = changes.match(/!\[([^\]]*)\]\(([^)\s]+)\)/);
  return match ? { alt: match[1], src: match[2] } : null;
};

/** How each kind of section looks; one the changelog has never used takes
 *  the plain look and its own name. */
const SECTION_LOOK: Record<string, { icon: LucideIcon; tone: string }> = {
  added: { icon: Gift, tone: "bg-primary/15 text-primary" },
  changed: { icon: RefreshCw, tone: "bg-sky-500/15 text-sky-600 dark:text-sky-400" },
  fixed: { icon: Wrench, tone: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400" },
  security: { icon: ShieldCheck, tone: "bg-amber-500/15 text-amber-600 dark:text-amber-400" },
  upgradenotes: { icon: TriangleAlert, tone: "bg-amber-500/15 text-amber-600 dark:text-amber-400" },
  deprecated: { icon: Archive, tone: "bg-muted text-muted-foreground" },
  removed: { icon: Minus, tone: "bg-muted text-muted-foreground" },
};
const PLAIN_LOOK = { icon: Info, tone: "bg-muted text-muted-foreground" };

/**
 * The changelog is written to be read in the repository, so its links point
 * at files there. Docs pages go to the published docs; anything else to the
 * file on GitHub, except the release's own pictures, which the app serves.
 */
const publishLinks = (changes: string): string =>
  changes.replace(/\]\((?!https?:|#|mailto:)([^)\s]+)\)/g, (whole, target: string) => {
    if (target.replace(/^\.\//, "").startsWith(RELEASE_IMAGE_DIR)) return whole;
    const [path, hash = ""] = target.split("#");
    const anchor = hash ? `#${hash}` : "";
    const docs = path.match(/^docs\/en\/(.+?)\.md$/);
    if (docs) {
      const page = docs[1] === "index" ? "" : `${docs[1].replace(/\/index$/, "")}/`;
      return `](${DOCS_URL}${page}${anchor})`;
    }
    return `](${REPO_URL}/blob/main/${path}${anchor})`;
  });

const useReleaseDate = () => {
  const { i18n } = useTranslation();
  return (date: string) => {
    const parsed = new Date(`${date}T12:00:00Z`);
    return Number.isNaN(parsed.getTime())
      ? date
      : dateTimeFormat(i18n.language, { dateStyle: "long", timeZone: "UTC" }).format(parsed);
  };
};

const Header = ({
  title,
  back,
  eyebrow,
  description,
  lifted = false,
  children,
}: {
  title: string;
  /** A way back, above everything else in the band. */
  back?: ReactNode;
  eyebrow?: ReactNode;
  /** Leave room under the band for a card that rises into it. */
  lifted?: boolean;
  description?: string;
  children?: ReactNode;
}) => (
  <DarkBand stars aria-labelledby="landing-whatsnew-title">
    <div
      className={cn(
        "relative mx-auto max-w-3xl px-4 pt-8 sm:px-8 sm:pt-12",
        lifted ? "pb-32 sm:pb-36" : "pb-10 sm:pb-12"
      )}
    >
      {back}
      {eyebrow ? (
        <p className="mb-3 font-semibold text-sky-300 text-sm uppercase tracking-widest">
          {eyebrow}
        </p>
      ) : null}
      <h1
        id="landing-whatsnew-title"
        className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
      >
        {title}
      </h1>
      {description ? (
        <p className="mt-4 max-w-2xl text-lg text-slate-300 sm:text-xl">{description}</p>
      ) : null}
      {children}
    </div>
  </DarkBand>
);

/** How much a release added, changed and fixed, as a row of pills. */
const Tally = ({ changes }: { changes: string }) => {
  const { t } = useTranslation("landing");
  const tally = tallyOf(changes);
  if (tally.length === 0) return null;
  return (
    <ul className="mt-3 flex flex-wrap gap-2 text-sm">
      {tally.map(({ key, count }) => (
        <li key={key} className="rounded-full border px-3 py-0.5 text-muted-foreground">
          {t(`whatsNew.tally.${key}`, { count })}
        </li>
      ))}
    </ul>
  );
};

/** The latest release, leading the list the way a blog leads with its
 *  newest post. It rises into the header band above it. */
const FeaturedPost = ({ entry }: { entry: ChangelogEntry }) => {
  const { t } = useTranslation("landing");
  const formatDate = useReleaseDate();
  const dark = useContext(ThemeContext)?.resolvedTheme === "dark";
  const cover = coverOf(entry.changes);
  const lead = changesOf(entry.changes).slice(0, FEATURE_HEADLINES);
  const shipped = useShipped(entry.version);
  return (
    <article
      className="relative -mt-28 overflow-hidden rounded-3xl border bg-card shadow-2xl sm:-mt-32"
      aria-labelledby={`post-${entry.version}`}
    >
      {cover ? (
        <img
          src={releaseImageUrl(cover.src, dark)}
          alt={cover.alt}
          className="aspect-video w-full border-b object-cover object-top"
        />
      ) : null}
      <div className="p-6 sm:p-10">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="rounded-full bg-primary px-2.5 py-0.5 font-semibold text-primary-foreground">
            {t("whatsNew.latest")}
          </span>
          <time dateTime={entry.date} className="text-muted-foreground">
            {formatDate(entry.date)}
          </time>
          {shipped.length > 0 ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-linear-to-r from-sky-500 via-blue-600 to-indigo-600 px-3 py-0.5 font-semibold text-white shadow-blue-600/40 shadow-lg">
              <Megaphone className="size-3.5" aria-hidden="true" />
              {t("whatsNew.shippedPill", { count: shipped.length })}
            </span>
          ) : null}
        </p>
        <h2
          id={`post-${entry.version}`}
          className="mt-3 font-bold text-3xl tracking-tight sm:text-4xl"
        >
          <Link
            to="/whats-new/$version"
            params={{ version: entry.version }}
            className="hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          >
            {t("whatsNew.postTitle", { version: entry.version })}
          </Link>
        </h2>
        <Tally changes={entry.changes} />
        {lead.length > 0 ? (
          <ul className="mt-6 divide-y border-y">
            {lead.map(({ headline, detail }) => (
              <li key={headline} className="py-4">
                <p className="font-medium leading-snug">{headline}</p>
                {detail ? (
                  <p className="mt-1 line-clamp-2 text-muted-foreground text-sm leading-relaxed">
                    {detail}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
        <Button asChild className="mt-6">
          <Link
            to="/whats-new/$version"
            params={{ version: entry.version }}
            aria-label={t("whatsNew.readMoreAria", { version: entry.version })}
          >
            {t("whatsNew.readMore")}
            <ArrowRight aria-hidden="true" />
          </Link>
        </Button>
      </div>
    </article>
  );
};

const PostCard = ({ entry }: { entry: ChangelogEntry }) => {
  const { t } = useTranslation("landing");
  const formatDate = useReleaseDate();
  const teaser = headlines(entry.changes).slice(0, TEASER_HEADLINES);
  return (
    <li>
      <article
        className="rounded-2xl border bg-card p-5 sm:p-6"
        aria-labelledby={`post-${entry.version}`}
      >
        <p className="text-muted-foreground text-sm">
          <time dateTime={entry.date}>{formatDate(entry.date)}</time>
        </p>
        <h3 id={`post-${entry.version}`} className="mt-1 font-semibold text-xl tracking-tight">
          <Link
            to="/whats-new/$version"
            params={{ version: entry.version }}
            className="hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          >
            {t("whatsNew.postTitle", { version: entry.version })}
          </Link>
        </h3>
        {teaser.length > 0 ? (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-muted-foreground">
            {teaser.map((headline) => (
              <li key={headline}>{headline}</li>
            ))}
          </ul>
        ) : null}
        <Link
          to="/whats-new/$version"
          params={{ version: entry.version }}
          className="mt-4 inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
          aria-label={t("whatsNew.readMoreAria", { version: entry.version })}
        >
          {t("whatsNew.readMore")}
          <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
      </article>
    </li>
  );
};

/** One change in a post: its headline, then what it says, pictures and all.
 *  The release's first change leads the post, set apart. */
const ChangeItem = ({ change, lead }: { change: Change; lead: boolean }) => {
  const { t } = useTranslation("landing");
  return (
    <li
      className={
        lead ? "my-6 rounded-2xl border border-primary/30 bg-primary/5 p-5 sm:p-7" : "py-7"
      }
    >
      {change.headline ? (
        <h3 className={cn("font-semibold tracking-tight", lead ? "text-2xl" : "text-xl")}>
          {change.headline}
        </h3>
      ) : null}
      {change.issues.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-2">
          {change.issues.map((issue) => (
            <li key={issue}>
              <a
                href={`${REPO_URL}/issues/${issue}`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-full bg-emerald-500/15 px-3 py-1 font-semibold text-emerald-700 text-sm hover:underline dark:text-emerald-300"
              >
                <CircleCheck className="size-4" aria-hidden="true" />
                {t("whatsNew.issue", { number: issue })}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
      {change.body ? (
        <div className={cn("text-muted-foreground leading-relaxed", change.headline && "mt-2")}>
          <Markdown surface="release" remoteImages content={publishLinks(change.body)} />
        </div>
      ) : null}
    </li>
  );
};

const PostSection = ({ section, leads }: { section: ReleaseSection; leads: boolean }) => {
  const { t } = useTranslation("landing");
  const { icon: Icon, tone } = SECTION_LOOK[section.key] ?? PLAIN_LOOK;
  const id = `section-${section.key}`;
  return (
    <section aria-labelledby={id}>
      <div className="flex items-center gap-3 border-b pb-4">
        <span className={cn("flex size-11 shrink-0 items-center justify-center rounded-xl", tone)}>
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <h2 id={id} className="font-semibold text-2xl tracking-tight">
          {t(`whatsNew.sections.${section.key}`, { defaultValue: section.name })}
        </h2>
        <span className="ml-auto rounded-full border px-3 py-0.5 text-muted-foreground text-sm tabular-nums">
          {section.changes.length}
        </span>
      </div>
      <ol className="divide-y">
        {section.changes.map((change, index) => (
          <ChangeItem key={change.headline || index} change={change} lead={leads && index === 0} />
        ))}
      </ol>
    </section>
  );
};

/** The suggestions that shipped in `version`, on Initiative Cloud, which
 *  alone has them; none anywhere else. */
const useShipped = (version: string) => {
  const onCloud = isCloudOrigin(useServer().getServerOrigin());
  const { data = [] } = useShippedIdeas(version, onCloud);
  return onCloud ? data : [];
};

/** The suggestions a release shipped, as loud as the page gets: a card that
 *  floats over the foot of the post's header, ahead of everything else it
 *  changed. */
const ShippedSuggestions = ({ shipped }: { shipped: IdeaRead[] }) => {
  const { t } = useTranslation(["landing", "intake"]);
  return (
    <section
      className="relative -mt-28 mb-12 rounded-3xl bg-linear-to-br from-[#1d2a5c] to-[#0b1224] p-6 text-white shadow-2xl ring-1 ring-white/15 sm:-mt-32 sm:p-8"
      aria-labelledby="shipped-suggestions"
    >
      <p className="font-semibold text-sky-300 text-sm uppercase tracking-widest">
        {t("intake:ideas.shippedTitle")}
      </p>
      <h2 id="shipped-suggestions" className="mt-2 font-bold text-3xl tracking-tight sm:text-4xl">
        {t("landing:whatsNew.shippedHeadline", { count: shipped.length })}
      </h2>
      <ul className="mt-6 flex flex-col gap-3">
        {shipped.map((idea) => (
          <li
            key={idea.task_id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white/5 px-4 py-3 ring-1 ring-white/15"
          >
            <Link
              to="/suggestions/$taskId"
              params={{ taskId: String(idea.task_id) }}
              className="font-semibold text-lg hover:underline"
            >
              {idea.title}
            </Link>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-primary px-3 py-1 font-semibold text-primary-foreground text-sm tabular-nums">
              <ThumbsUp className="size-4" aria-hidden="true" />
              {t("intake:ideas.votes", { count: idea.votes })}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
};

export const WhatsNewPage = () => {
  const { t } = useTranslation("landing");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data, isLoading, isError, isFetching, refetch } = useChangelog({ limit });
  const entries = data?.entries ?? [];
  const [latest, ...earlier] = entries;
  usePageMeta(t("whatsNew.metaTitle"), t("whatsNew.description"));

  return (
    <SiteShell current="whats-new">
      <Header
        title={t("whatsNew.title")}
        description={t("whatsNew.description")}
        lifted={Boolean(latest)}
      />
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8 sm:py-14">
        {isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={3} avatar={false} rowClassName="rounded-2xl border bg-card p-5" />
          </SkeletonRegion>
        ) : isError ? (
          <StatusMessage onRetry={refetch} />
        ) : !latest ? (
          <p className="text-center text-muted-foreground">{t("whatsNew.empty")}</p>
        ) : (
          <>
            <FeaturedPost entry={latest} />
            {earlier.length > 0 ? (
              <section className="mt-16" aria-labelledby="whatsnew-earlier">
                <h2
                  id="whatsnew-earlier"
                  className="mb-4 font-semibold text-muted-foreground text-sm uppercase tracking-widest"
                >
                  {t("whatsNew.earlier")}
                </h2>
                <ul className="flex flex-col gap-4">
                  {earlier.map((entry) => (
                    <PostCard key={entry.version} entry={entry} />
                  ))}
                </ul>
              </section>
            ) : null}
            {/* A full page means there may be more behind it. */}
            {entries.length === limit ? (
              <div className="mt-8 text-center">
                <Button
                  variant="outline"
                  onClick={() => setLimit((value) => value + PAGE_SIZE)}
                  disabled={isFetching}
                >
                  {t("whatsNew.older")}
                </Button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </SiteShell>
  );
};

export const WhatsNewPostPage = () => {
  const { t } = useTranslation("landing");
  const { version } = useParams({ strict: false }) as { version: string };
  const { data, isLoading, isError, refetch } = useChangelog({ version });
  const entry = data?.entries[0];
  const formatDate = useReleaseDate();
  const title = t("whatsNew.postTitle", { version });
  const sections = entry ? sectionsOf(entry.changes) : [];
  const shipped = useShipped(version);
  usePageMeta(
    t("whatsNew.postMetaTitle", { version }),
    entry
      ? headlines(entry.changes).slice(0, TEASER_HEADLINES).join(". ")
      : t("whatsNew.description")
  );

  return (
    <SiteShell current="whats-new">
      <Header
        title={title}
        back={
          <Link
            to="/whats-new"
            className="mb-6 inline-flex items-center gap-1.5 font-semibold text-sky-300 text-sm hover:text-white hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {t("whatsNew.back")}
          </Link>
        }
        eyebrow={
          <>
            {t("whatsNew.releaseNotes")}
            {entry ? (
              <time
                dateTime={entry.date}
                className="ml-3 font-normal text-slate-300 normal-case tracking-normal"
              >
                {formatDate(entry.date)}
              </time>
            ) : null}
          </>
        }
        lifted={Boolean(entry) && shipped.length > 0}
      />
      <div className="mx-auto max-w-3xl px-4 pt-8 pb-10 sm:px-8 sm:pt-10 sm:pb-14">
        {isLoading ? (
          <SkeletonRegion>
            <SkeletonLines lines={8} />
          </SkeletonRegion>
        ) : isError ? (
          <StatusMessage onRetry={refetch} />
        ) : entry ? (
          <>
            {shipped.length > 0 ? <ShippedSuggestions shipped={shipped} /> : null}
            <article className="flex flex-col gap-14">
              {sections.map((section, index) => (
                <PostSection key={section.key} section={section} leads={index === 0} />
              ))}
            </article>
          </>
        ) : (
          <p className="text-muted-foreground">{t("whatsNew.notFound")}</p>
        )}
      </div>
    </SiteShell>
  );
};

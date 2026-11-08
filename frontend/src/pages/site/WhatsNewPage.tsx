/**
 * What's new: the changelog, as posts.
 *
 * Each released version is one post, newest first, read from the changelog
 * the server ships with. The list shows a release's first few headlines as
 * its teaser; a post shows the whole release. The unreleased section isn't
 * a post, since nobody can have it yet.
 */

import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { ChangelogEntry } from "@/api/generated/initiativeAPI.schemas";
import { Markdown } from "@/components/markdown/Markdown";
import { useChangelog } from "@/hooks/useSettings";
import { DOCS_URL, REPO_URL } from "@/lib/links";
import { RELEASE_IMAGE_DIR } from "@/lib/releaseImages";
import { Button } from "@/ui/button";
import { dateTimeFormat } from "@/ui/lib/intl";
import { ListSkeleton, SkeletonLines, SkeletonRegion } from "@/ui/page-skeletons";
import { StatusMessage } from "@/ui/status-message";

import { DarkBand } from "./DarkBand";
import { SiteShell } from "./SiteShell";
import { usePageMeta } from "./usePageMeta";

const PAGE_SIZE = 10;
const TEASER_HEADLINES = 3;

/** The bold lead of each top-level bullet: how a release names its changes. */
const headlines = (changes: string): string[] =>
  [...changes.matchAll(/^- \*\*(.+?)\*\*/gm)].map((match) => match[1].replace(/[.:]$/, ""));

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

/** A release as a post: links published, and its sections one level under
 *  the post's title rather than two. */
const asPost = (changes: string): string => publishLinks(changes).replace(/^### /gm, "## ");

const useReleaseDate = () => {
  const { i18n } = useTranslation();
  return (date: string) => {
    const parsed = new Date(`${date}T12:00:00Z`);
    return Number.isNaN(parsed.getTime())
      ? date
      : dateTimeFormat(i18n.language, { dateStyle: "long", timeZone: "UTC" }).format(parsed);
  };
};

const Header = ({ title, description }: { title: string; description?: string }) => (
  <DarkBand stars aria-labelledby="landing-whatsnew-title">
    <div className="relative mx-auto max-w-3xl px-4 pt-10 pb-14 sm:px-8 sm:pt-18 sm:pb-18">
      <h1
        id="landing-whatsnew-title"
        className="font-extrabold text-[2.6rem] leading-tight tracking-tight sm:text-6xl"
      >
        {title}
      </h1>
      {description ? <p className="mt-4 text-lg text-slate-300">{description}</p> : null}
    </div>
  </DarkBand>
);

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
        <h2 id={`post-${entry.version}`} className="mt-1 font-extrabold text-2xl tracking-tight">
          <Link
            to="/whats-new/$version"
            params={{ version: entry.version }}
            className="hover:underline focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2"
          >
            {t("whatsNew.postTitle", { version: entry.version })}
          </Link>
        </h2>
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

export const WhatsNewPage = () => {
  const { t } = useTranslation("landing");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const { data, isLoading, isError, isFetching, refetch } = useChangelog({ limit });
  const entries = data?.entries ?? [];
  usePageMeta(t("whatsNew.metaTitle"), t("whatsNew.description"));

  return (
    <SiteShell current="whats-new">
      <Header title={t("whatsNew.title")} description={t("whatsNew.description")} />
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8 sm:py-14">
        {isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={3} avatar={false} rowClassName="rounded-2xl border bg-card p-5" />
          </SkeletonRegion>
        ) : isError ? (
          <StatusMessage onRetry={refetch} />
        ) : entries.length === 0 ? (
          <p className="text-center text-muted-foreground">{t("whatsNew.empty")}</p>
        ) : (
          <>
            <ul className="flex flex-col gap-4">
              {entries.map((entry) => (
                <PostCard key={entry.version} entry={entry} />
              ))}
            </ul>
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
  usePageMeta(
    t("whatsNew.postMetaTitle", { version }),
    entry
      ? headlines(entry.changes).slice(0, TEASER_HEADLINES).join(". ")
      : t("whatsNew.description")
  );

  return (
    <SiteShell current="whats-new">
      <Header title={title} description={entry ? formatDate(entry.date) : undefined} />
      <div className="mx-auto max-w-3xl px-4 py-10 sm:px-8 sm:py-14">
        <Link
          to="/whats-new"
          className="mb-6 inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          {t("whatsNew.back")}
        </Link>
        {isLoading ? (
          <SkeletonRegion>
            <SkeletonLines lines={8} />
          </SkeletonRegion>
        ) : isError ? (
          <StatusMessage onRetry={refetch} />
        ) : entry ? (
          <article>
            <Markdown surface="release" remoteImages content={asPost(entry.changes)} />
          </article>
        ) : (
          <p className="text-muted-foreground">{t("whatsNew.notFound")}</p>
        )}
      </div>
    </SiteShell>
  );
};

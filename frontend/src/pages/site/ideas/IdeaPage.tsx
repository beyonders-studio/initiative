/**
 * One suggestion, where a voter's notice leads. The band carries the way
 * back, its category and status, and its title; the card its description as
 * the team wrote it, the upvote, a way to add one's own words to it, and the
 * release it shipped in, where it has. Its description reads as written, with
 * any mention or link in it as plain text: nothing it names is the reader's
 * to open.
 */

import { Link, Navigate, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { IdeaMeta, VoteButton } from "@/components/ideas/IdeaParts";
import { Markdown } from "@/components/markdown/Markdown";
import { useIdea } from "@/hooks/useIdeas";
import { useServer } from "@/hooks/useServer";
import { isCloudOrigin } from "@/lib/cloud";
import { DarkBand } from "@/pages/site/DarkBand";
import { SiteShell } from "@/pages/site/SiteShell";
import { Button } from "@/ui/button";

export const IdeaPage = () => {
  const { t } = useTranslation("intake");
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  const { getServerOrigin } = useServer();
  const { data: idea, isError } = useIdea(Number(taskId));

  if (!isCloudOrigin(getServerOrigin())) return <Navigate to="/" replace />;
  if (isError) return <Navigate to="/suggestions" replace />;
  // A suggestion joined into another answers with the one it joined.
  if (idea && String(idea.task_id) !== taskId) {
    return <Navigate to="/suggestions/$taskId" params={{ taskId: String(idea.task_id) }} replace />;
  }

  return (
    <SiteShell current="suggestions">
      <DarkBand stars aria-labelledby={idea ? "suggestion-title" : undefined}>
        <div className="relative mx-auto max-w-3xl px-4 pt-8 pb-24 sm:px-8 sm:pt-12 sm:pb-28">
          <Link
            to="/suggestions"
            className="inline-flex items-center gap-1.5 font-semibold text-sky-300 text-sm hover:underline"
          >
            <ArrowLeft className="size-4" aria-hidden />
            {t("ideas.back")}
          </Link>
          {idea ? (
            <>
              <div className="mt-5">
                <IdeaMeta idea={idea} onDark />
              </div>
              <h1
                id="suggestion-title"
                className="mt-3 font-extrabold text-3xl leading-tight tracking-tight sm:text-5xl"
              >
                {idea.title}
              </h1>
            </>
          ) : null}
        </div>
      </DarkBand>
      <div className="mx-auto max-w-3xl px-4 pb-20 sm:px-8 sm:pb-24">
        <div className="relative -mt-12 rounded-3xl border bg-card p-5 shadow-xl sm:p-8">
          {idea ? (
            <>
              <Markdown content={idea.description ?? ""} disableLinks />
              <div className="mt-6 flex flex-wrap items-center gap-3 border-t pt-6">
                <VoteButton idea={idea} next={`/suggestions/${idea.task_id}`} size="lg" />
                <Button variant="outline" className="h-11 sm:h-9" asChild>
                  <Link to="/feedback" search={{ idea: idea.task_id }}>
                    {t("ideas.addThoughts")}
                  </Link>
                </Button>
                {idea.release ? (
                  <Link
                    to="/whats-new/$version"
                    params={{ version: idea.release }}
                    className="font-semibold text-primary text-sm hover:underline"
                  >
                    {t("ideas.shippedIn", { version: idea.release })}
                  </Link>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </SiteShell>
  );
};

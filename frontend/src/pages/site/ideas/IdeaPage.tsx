/**
 * One published idea, where a voter's notice leads: its status, its title and
 * description as the team wrote them, how many voted, and the vote button.
 * Its description reads as written, with any mention or link in it as plain
 * text: nothing it names is the reader's to open.
 */

import { Link, Navigate, useParams } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SignInFrame } from "@/components/auth/SignInFrame";
import { IdeaStatusBadge, VoteButton } from "@/components/ideas/IdeaParts";
import { Markdown } from "@/components/markdown/Markdown";
import { useIdea } from "@/hooks/useIdeas";
import { Card } from "@/ui/card";

export const IdeaPage = () => {
  const { t } = useTranslation("intake");
  const { taskId } = useParams({ from: "/_serverRequired/ideas/$taskId" });
  const { data: idea, isError } = useIdea(Number(taskId));

  if (isError) return <Navigate to="/ideas" replace />;
  // An idea joined into another answers with the one it joined.
  if (idea && String(idea.task_id) !== taskId) {
    return <Navigate to="/ideas/$taskId" params={{ taskId: String(idea.task_id) }} replace />;
  }

  return (
    <SignInFrame fillPhone>
      <Card className="w-full max-w-2xl space-y-4 p-4 max-sm:min-h-app max-sm:rounded-none max-sm:border-0 sm:p-6">
        <Link
          to="/ideas"
          className="inline-flex items-center gap-1 text-muted-foreground text-sm hover:underline"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("ideas.all")}
        </Link>
        {idea ? (
          <>
            <div className="space-y-2">
              <IdeaStatusBadge status={idea.status} />
              <h1 className="font-semibold text-xl">{idea.title}</h1>
            </div>
            <Markdown content={idea.description ?? ""} disableLinks />
            <div className="flex flex-wrap items-center gap-3">
              <VoteButton idea={idea} next={`/ideas/${idea.task_id}`} />
              <span className="text-muted-foreground text-sm">
                {t("ideas.votes", { count: idea.votes })}
              </span>
            </div>
          </>
        ) : null}
      </Card>
    </SignInFrame>
  );
};

/**
 * An Ideas-board task's panel, on the task the team writes the idea in:
 * whether it is published, which shows its title, description and status to
 * everybody on the Ideas page, and how many voted. A task anywhere else has
 * none.
 */

import { Lightbulb } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePublishTaskIdea, useTaskIdea } from "@/hooks/useIdeas";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

export const IdeaPanel = ({ taskId, canEdit }: { taskId: number; canEdit: boolean }) => {
  const { t } = useTranslation("intake");
  const { data } = useTaskIdea(taskId);
  const publish = usePublishTaskIdea(taskId, {
    onError: (err) => toast.error(getErrorMessage(err, "intake:idea.error")),
  });
  if (!data) return null;
  const published = data.published_at != null;
  const switchId = `idea-published-${taskId}`;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Lightbulb className="h-4 w-4" aria-hidden="true" />
          {t("idea.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center gap-3">
          <Switch
            id={switchId}
            checked={published}
            disabled={!canEdit || publish.isPending}
            onCheckedChange={(on) => publish.mutate(on)}
          />
          <Label htmlFor={switchId}>{t("idea.publish")}</Label>
        </div>
        <p className="text-muted-foreground">
          {published ? t("idea.publishedHelp") : t("idea.draftHelp")}
        </p>
        <p>{t("idea.votes", { count: data.votes })}</p>
      </CardContent>
    </Card>
  );
};

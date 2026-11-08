import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { useToolSettings } from "@/components/tools/settings/ToolSettingsContext";
import { useSetPostReactions } from "@/hooks/usePostReactions";
import { usePost } from "@/hooks/usePosts";
import { Label } from "@/ui/label";
import { Switch } from "@/ui/switch";

/**
 * Whether a post takes reactions of its own, in its Details card. Everywhere
 * else reactions hang off a comment, and the comment switch answers for them.
 * Saved on flip: the switch shows the new state at once and puts the old one
 * back if the write fails.
 */
export const PostReactionsField = () => {
  const { t } = useTranslation("common");
  const { entity } = useToolSettings();
  const saved = usePost(entity.id).data?.reactions_enabled ?? true;
  const [enabled, setEnabled] = useState(saved);
  useEffect(() => setEnabled(saved), [saved]);
  const setReactions = useSetPostReactions();

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="space-y-1">
        <Label htmlFor="post-reactions-enabled">{t("toolSettings.reactions")}</Label>
        <p className="text-muted-foreground text-xs">{t("toolSettings.reactionsDescription")}</p>
      </div>
      <Switch
        id="post-reactions-enabled"
        checked={enabled}
        onCheckedChange={(value) => {
          setEnabled(value);
          setReactions.mutate(
            { id: entity.id, enabled: value },
            { onError: () => setEnabled(saved) }
          );
        }}
        disabled={!entity.can.edit || setReactions.isPending}
      />
    </div>
  );
};

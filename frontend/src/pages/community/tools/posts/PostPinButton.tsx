import { Pin, PinOff } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { PostRead } from "@/api/generated/initiativeAPI.schemas";
import { useSetPostPin } from "@/hooks/usePosts";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";

/**
 * Pins a notice to the top of its board, or takes it down. An icon on the
 * board's card; `labelled` on the notice's own page, where there is room to
 * say it.
 */
export const PostPinButton = ({
  post,
  labelled = false,
}: {
  post: PostRead;
  labelled?: boolean;
}) => {
  const { t } = useTranslation("posts");
  const setPin = useSetPostPin(post.id, {
    onSuccess: (updated) =>
      toast.success(updated.is_pinned ? t("pin.pinnedToast") : t("pin.unpinnedToast")),
  });
  const label = post.is_pinned ? t("pin.unpin") : t("pin.pin");
  const Icon = post.is_pinned ? PinOff : Pin;

  return (
    <Button
      variant={labelled ? "outline" : "ghost"}
      size="sm"
      disabled={setPin.isPending}
      aria-label={labelled ? undefined : label}
      onClick={() => setPin.mutate({ pinned: !post.is_pinned })}
    >
      <Icon className="h-4 w-4" aria-hidden />
      {labelled && label}
    </Button>
  );
};

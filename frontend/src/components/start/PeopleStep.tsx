import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { createCommunityInvite } from "@/api/generated/communities/communities";
import { PATH_SCENES, PATH_TINTS, PixelScene } from "@/components/start/PixelScene";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { cn } from "@/ui/lib/utils";

/** A burst of confetti for a finished community, for anybody who has not
 *  asked their system for less motion. */
const celebrate = () => {
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) return;
  void import("@/components/effects/runConfetti")
    .then(({ runConfetti }) => runConfetti("default"))
    .catch(() => undefined);
};

/** The new community's first invite link, to copy and send. */
export const PeopleStep = ({
  communityId,
  origin,
  planButton,
  onDone,
  doneLabel,
}: {
  communityId: number;
  origin: string;
  /** Shown when a plan was picked but its tab could not be opened. */
  planButton?: () => void;
  onDone: () => void;
  doneLabel: string;
}) => {
  const { t } = useTranslation(["auth", "common", "communities"]);
  const [link, setLink] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const asked = useRef(false);

  useEffect(() => {
    if (asked.current) return;
    asked.current = true;
    celebrate();
    // One link for the whole group, so it takes any number of people.
    createCommunityInvite(communityId, { max_uses: null })
      .then((invite) => setLink(`${origin}/invite/${encodeURIComponent(invite.code)}`))
      .catch(() => setFailed(true));
  }, [communityId, origin]);

  const copy = async () => {
    if (!link) return;
    await navigator.clipboard.writeText(link);
    toast.success(t("communities:inviteLinkCopied"));
  };

  return (
    <>
      {failed ? (
        <p className="text-muted-foreground text-sm">{t("start.people.linkError")}</p>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border-2 border-dashed p-3">
          <span
            className={cn(
              // Left out on phones, where the link needs the room.
              "hidden size-14 shrink-0 place-items-center rounded-lg sm:grid",
              PATH_TINTS.invite
            )}
          >
            <PixelScene scene={PATH_SCENES.invite} className="w-10" />
          </span>
          <Field label={t("start.people.linkLabel")} className="min-w-0 flex-1">
            <div className="flex gap-2">
              <Input value={link ?? ""} readOnly className="min-w-0" />
              <Button type="button" variant="outline" onClick={() => void copy()} disabled={!link}>
                {t("common:copy")}
              </Button>
            </div>
          </Field>
        </div>
      )}
      {planButton ? (
        <Button type="button" variant="outline" className="w-full" onClick={planButton}>
          {t("start.people.choosePlan")}
        </Button>
      ) : null}
      <Button type="button" className="w-full" onClick={onDone}>
        {doneLabel}
      </Button>
    </>
  );
};

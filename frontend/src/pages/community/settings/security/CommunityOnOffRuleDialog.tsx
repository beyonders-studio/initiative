import { useState } from "react";
import { useTranslation } from "react-i18next";

import { OnOffRuleDialog } from "@/components/settings/OnOffRuleDialog";
import { useCommunities } from "@/hooks/useCommunities";
import { useUpdateCommunityAuthSettings } from "@/hooks/useCommunityAuthPolicy";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Alert, AlertDescription } from "@/ui/alert";

import { readUnmet, type Unmet, UnmetAlert } from "./UnmetAlert";

/**
 * A rule of the community's that is on or off: the second factor, or signing
 * in again every twelve hours. Saving one is asked of whoever saves it.
 */
export const CommunityOnOffRuleDialog = ({
  communityId,
  rule,
  saved,
  impact,
  open,
  onOpenChange,
}: {
  communityId: number;
  rule: "require_second_factor" | "enforce_compliance_session";
  saved: boolean;
  /** What turning it on reaches, a line each. */
  impact: (string | false)[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation("settings");
  const { activeCommunity, refreshCommunities } = useCommunities();
  const copy =
    rule === "require_second_factor" ? "communityAuth.secondFactor" : "communityAuth.sessionLimit";
  const [error, setError] = useState<string | null>(null);
  const [unmet, setUnmet] = useState<Unmet | null>(null);
  const update = useUpdateCommunityAuthSettings(communityId);

  const forget = () => {
    setError(null);
    setUnmet(null);
  };
  const close = () => {
    onOpenChange(false);
    forget();
  };

  const save = (on: boolean) =>
    update.mutate(
      rule === "require_second_factor"
        ? { require_second_factor: on }
        : { enforce_compliance_session: on },
      {
        onSuccess: async () => {
          // A member's community list carries these too, for the pages that
          // read them there.
          if (activeCommunity?.grantSettingsLevel !== "superadmin") await refreshCommunities();
          toast.success(t(`${copy}.saved`));
          close();
        },
        onError: (err: unknown) => {
          const found = readUnmet(err);
          setUnmet(found);
          setError(found ? null : getErrorMessage(err, `settings:${copy}.error`));
        },
      }
    );

  return (
    <OnOffRuleDialog
      id={rule}
      title={t(`${copy}.title`)}
      description={t(`${copy}.description`, { community: activeCommunity?.name ?? "" })}
      onLabel={t(`${copy}.onLabel`)}
      offLabel={t(`${copy}.offLabel`)}
      saved={saved}
      impact={impact}
      pending={update.isPending}
      onSave={save}
      onChoose={forget}
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
    >
      {unmet && <UnmetAlert communityId={communityId} unmet={unmet} />}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </OnOffRuleDialog>
  );
};

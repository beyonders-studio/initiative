import { useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityRead } from "@/api/generated/initiativeAPI.schemas";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { readOptionalWholeNumber } from "@/lib/text";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { Switch } from "@/ui/switch";

const DEFAULT_DAYS = 90;
const MIN_DAYS = 1;
const MAX_DAYS = 3650;

/**
 * The community's trash retention, as one row above its trash: deleted items
 * are removed for good after a number of days, or, with the switch off, kept
 * until somebody deletes them.
 */
export const RetentionSetting = () => {
  const { activeCommunity, updateCommunityInState } = useCommunities();
  if (!activeCommunity) return null;

  // Keyed by community, so switching communities starts from that one's figure.
  return (
    <RetentionForm
      key={activeCommunity.id}
      community={activeCommunity}
      onSaved={updateCommunityInState}
    />
  );
};

const RetentionForm = ({
  community,
  onSaved,
}: {
  community: CommunityRead;
  onSaved: (community: CommunityRead) => void;
}) => {
  const { t } = useTranslation(["communities", "common"]);
  const stored = community.retention_days;
  const [autoPurge, setAutoPurge] = useState(stored !== null);
  const [days, setDays] = useState(String(stored ?? DEFAULT_DAYS));
  const [saving, setSaving] = useState(false);

  const { value: parsed, valid } = readOptionalWholeNumber(days, MIN_DAYS, MAX_DAYS);
  const next = autoPurge ? parsed : null;
  const ready = !autoPurge || (valid && parsed !== null);

  const save = async () => {
    setSaving(true);
    try {
      onSaved(await updateCommunity(community.id, { retention_days: next }));
      toast.success(t("settings.retentionUpdatedSuccessfully"));
    } catch (err) {
      toast.error(getErrorMessage(err, "communities:settings.unableToUpdate"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b pb-4">
      <Switch
        checked={autoPurge}
        onCheckedChange={setAutoPurge}
        aria-labelledby="trash-retention"
      />
      <span id="trash-retention" className="flex items-center gap-2 font-medium text-sm">
        <Trans
          t={t}
          i18nKey="settings.retentionAfter"
          count={parsed ?? 0}
          components={{
            days: (
              <Input
                type="number"
                min={MIN_DAYS}
                max={MAX_DAYS}
                value={days}
                disabled={!autoPurge}
                onChange={(event) => setDays(event.target.value)}
                aria-label={t("settings.retentionDaysLabel")}
                className="h-8 w-20"
              />
            ),
          }}
        />
      </span>
      <Button size="sm" onClick={save} disabled={saving || !ready || next === stored}>
        {saving ? t("settings.saving") : t("common:save")}
      </Button>
    </div>
  );
};

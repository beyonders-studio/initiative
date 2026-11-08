import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityUpdate } from "@/api/generated/initiativeAPI.schemas";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { CommunityArtworkPanel } from "@/pages/community/settings/community/CommunityArtworkPanel";
import { CommunityDiscoveryPanel } from "@/pages/community/settings/community/CommunityDiscoveryPanel";
import { CommunityLocationPanel } from "@/pages/community/settings/community/CommunityLocationPanel";
import { Button } from "@/ui/button";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Textarea } from "@/ui/textarea";

export const CommunityPage = () => {
  const { activeCommunity, refreshCommunities, updateCommunityInState } = useCommunities();
  const { t } = useTranslation(["communities", "common"]);
  const [name, setName] = useState(activeCommunity?.name ?? "");
  const [description, setDescription] = useState(activeCommunity?.description ?? "");
  const save = useCommunityMutation({
    mutationFn: async (communityId, body: CommunityUpdate) => {
      updateCommunityInState(await updateCommunity(communityId, body));
      await refreshCommunities();
    },
  });

  const [prevCommunity, setPrevCommunity] = useState(activeCommunity);
  if (prevCommunity !== activeCommunity) {
    setPrevCommunity(activeCommunity);
    setName(activeCommunity?.name ?? "");
    setDescription(activeCommunity?.description ?? "");
  }

  const handleSave = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    save.mutate({ name, description });
  };

  if (!activeCommunity) {
    return (
      <div className="space-y-6">
        <h2 className="font-semibold text-xl tracking-tight">{t("settings.title")}</h2>
        <p className="text-muted-foreground text-sm">{t("settings.noActiveCommunity")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SettingsSection>
        <form className="space-y-4" onSubmit={handleSave}>
          <Field label={t("settings.nameLabel")}>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={255}
              required
            />
          </Field>
          <Field label={t("settings.descriptionLabel")}>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
            />
          </Field>
          {save.error ? (
            <p className="text-destructive text-sm">
              {getErrorMessage(save.error, "communities:settings.unableToUpdate")}
            </p>
          ) : null}
          {save.isSuccess ? (
            <p className="text-primary text-sm">{t("settings.updatedSuccessfully")}</p>
          ) : null}
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? t("settings.saving") : t("settings.saveChanges")}
          </Button>
        </form>
      </SettingsSection>
      <CommunityLocationPanel />
      <CommunityArtworkPanel community={activeCommunity} />
      <CommunityDiscoveryPanel />
    </div>
  );
};

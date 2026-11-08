import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { updateCommunity } from "@/api/generated/communities/communities";
import type { CommunityUpdate } from "@/api/generated/initiativeAPI.schemas";
import { CommunityArtworkPanel } from "@/components/communities/CommunityArtworkPanel";
import { CommunityDiscoveryPanel } from "@/components/communities/CommunityDiscoveryPanel";
import { CommunityLocationPanel } from "@/components/communities/CommunityLocationPanel";
import { useCommunityMutation } from "@/hooks/useApiMutation";
import { useCommunities } from "@/hooks/useCommunities";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Card, CardContent } from "@/ui/card";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Textarea } from "@/ui/textarea";

export const SettingsCommunityPage = () => {
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
      <Card>
        <CardContent className="pt-6">
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
        </CardContent>
      </Card>
      <CommunityLocationPanel />
      <CommunityArtworkPanel community={activeCommunity} />
      <CommunityDiscoveryPanel />
    </div>
  );
};

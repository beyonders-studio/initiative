/**
 * What a community inherits for a provider it has not spoken about.
 *
 * One organisation running its own deployment has one identity provider and
 * one tenant, and its communities are its teams. Answering here once spares
 * every team repeating the same two facts, and spares the operator being their
 * queue — which is the thing this whole arrangement exists to avoid.
 *
 * A community's own connection replaces this outright. Nothing merges, and a
 * community that connects with the button off has declined it.
 *
 * There is deliberately no auto-join here: an answer names a provider, never a
 * community, so joining on it would place an arrival in every community that
 * had not spoken.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AuthProviderOwnerRead } from "@/api/generated/initiativeAPI.schemas";
import {
  useAuthProviders,
  useClearProviderDefault,
  useProviderDefault,
  useSetProviderDefault,
} from "@/hooks/useSettings";
import { toast } from "@/lib/mascotToast";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";

const ProviderDefaultRow = ({ provider }: { provider: AuthProviderOwnerRead }) => {
  const { t } = useTranslation("settings");
  const defaultQuery = useProviderDefault(provider.id);
  const setDefault = useSetProviderDefault(provider.id);
  const clearDefault = useClearProviderDefault(provider.id);

  const current = defaultQuery.data ?? null;
  const [editing, setEditing] = useState(false);
  const [claim, setClaim] = useState("");
  const [claimValues, setClaimValues] = useState("");

  const open = () => {
    setClaim(current?.claim ?? "");
    setClaimValues((current?.claim_values ?? []).join(", "));
    setEditing(true);
  };

  const save = () => {
    const values = claimValues
      .split(/[\s,]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    setDefault.mutate(
      {
        // Both halves or neither, the same rule a community's own is held to.
        claim: claim && values.length > 0 ? claim : null,
        claim_values: claim && values.length > 0 ? values : null,
      },
      {
        onSuccess: () => {
          toast.success(t("providerDefaults.saved"));
          setEditing(false);
        },
      }
    );
  };

  return (
    <li className="space-y-3 px-3 py-3">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <span className="font-medium">{provider.display_name}</span>
          <p className="text-muted-foreground text-sm">
            {current
              ? current.claim && current.claim_values.length > 0
                ? t("providerDefaults.narrowedTo", {
                    claim: current.claim,
                    values: current.claim_values.join(", "),
                  })
                : t("providerDefaults.anyoneItVouchesFor")
              : t("providerDefaults.noAnswer")}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={open}>
            {current ? t("providerDefaults.change") : t("providerDefaults.answer")}
          </Button>
          {current && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-destructive"
              onClick={() =>
                clearDefault.mutate(undefined, {
                  onSuccess: () => toast.success(t("providerDefaults.withdrawn")),
                })
              }
            >
              {t("providerDefaults.withdraw")}
            </Button>
          )}
        </div>
      </div>

      {editing && (
        <div className="space-y-3 rounded-md border bg-muted/40 p-3">
          <Field label={t("providerDefaults.claimLabel")}>
            <Input
              value={claim}
              onChange={(event) => setClaim(event.target.value)}
              placeholder="tid"
            />
          </Field>
          <Field label={t("providerDefaults.valuesLabel")} hint={t("providerDefaults.valuesHint")}>
            <Input value={claimValues} onChange={(event) => setClaimValues(event.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setEditing(false)}>
              {t("authProviders.cancel")}
            </Button>
            <Button type="button" size="sm" onClick={save} disabled={setDefault.isPending}>
              {t("providerDefaults.save")}
            </Button>
          </div>
        </div>
      )}
    </li>
  );
};

export const ProviderDefaultsSection = () => {
  const { t } = useTranslation("settings");
  const providersQuery = useAuthProviders();
  const providers = providersQuery.data ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("providerDefaults.title")}</CardTitle>
        <CardDescription>{t("providerDefaults.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {providersQuery.isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={3} />
          </SkeletonRegion>
        ) : providers.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("providerDefaults.noProviders")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {providers.map((provider) => (
              <ProviderDefaultRow key={provider.id} provider={provider} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
};

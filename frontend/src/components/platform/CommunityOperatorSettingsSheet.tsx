/**
 * Everything an operator sets for one community, in one place.
 *
 * These are the settings a community's own admins cannot reach: the caps, what
 * it may do about its own sign-in, and which features it has. They used to be
 * a column each in the Communities table, which stopped scaling — the banner
 * entitlement shipped with no control at all because there was nowhere to put
 * it. A table row is a poor form, and the set only grows.
 *
 * Each control saves on its own, the way the cells did: the operator endpoint
 * takes any subset, so there is no Save button to forget and no dirty state to
 * lose.
 *
 * Where the billing service sets each community's plan, the caps and
 * entitlements are the plan's: they are shown, not set, and a button opens the
 * community in billing to change them.
 */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityAuthOption,
  PlatformCommunityStorageRead,
  PluginSummaryRead,
} from "@/api/generated/initiativeAPI.schemas";
import { CommunityAction, CommunityStatus } from "@/api/generated/initiativeAPI.schemas";
import {
  useListCommunityPluginSummaries,
  useReadCommunityPluginSummary,
} from "@/api/generated/settings/settings";
import { PluginSummaryFigures } from "@/components/communities/PluginSummaryCards";
import { BillingConsoleButton, opensBillingHere } from "@/components/platform/BillingConsoleButton";
import { CommunityRestoreWizard } from "@/components/platform/CommunityRestoreWizard";
import { Section, SettingRow } from "@/components/platform/SettingRow";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useServerForm } from "@/hooks/useServerForm";
import {
  useAgreeCommunityNarrowing,
  useCommunityNarrowings,
  useUpdateCommunityStorage,
} from "@/hooks/useSettings";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDate } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";

const GIB = 1024 ** 3;

const parseGbInput = (raw: string): { bytes: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { bytes: null, invalid: false }; // blank = unlimited
  const gb = Number(trimmed);
  if (!Number.isFinite(gb) || gb < 0) return { bytes: null, invalid: true };
  return { bytes: Math.round(gb * GIB), invalid: false };
};

const bytesToGbInput = (bytes: number | null): string =>
  bytes == null ? "" : String(Number((bytes / GIB).toFixed(2)));

const parseUserLimitInput = (raw: string): { limit: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { limit: null, invalid: false }; // blank = unlimited
  const n = Number(trimmed);
  if (!Number.isInteger(n) || n < 1) return { limit: null, invalid: true };
  return { limit: n, invalid: false };
};

const userLimitToInput = (limit: number | null): string => (limit == null ? "" : String(limit));

/** Parse the guest cap. Blank = unlimited (null); 0 takes no new guests, so
 *  unlike the member cap it is a value of its own. */
const parseGuestLimitInput = (raw: string): { limit: number | null; invalid: boolean } => {
  const trimmed = raw.trim();
  if (trimmed === "") return { limit: null, invalid: false };
  const n = Number(trimmed);
  if (!Number.isInteger(n) || n < 0) return { limit: null, invalid: true };
  return { limit: n, invalid: false };
};

export const CommunityOperatorSettingsSheet = ({
  community,
  open,
  onOpenChange,
  supportBound,
}: {
  community: PlatformCommunityStorageRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether the deployment has somewhere to send help requests. Help
   *  requests become cases in its support stream, so the switch is only
   *  meaningful once something is bound to receive them — the deployment's
   *  binding, one for every community, served beside the list. */
  supportBound: boolean;
}) => {
  const { t } = useTranslation("settings");
  const { billing } = useAppConfig();
  const planIsBillings = billing?.manages_plans ?? false;

  // The drafts follow whichever community the sheet was opened for, and show
  // what is stored once a save lands — a normalised value ("10.0" -> "10")
  // included.
  const form = useServerForm(
    community ?? undefined,
    (loaded) => ({
      storage: bytesToGbInput(loaded?.max_storage_bytes ?? null),
      users: userLimitToInput(loaded?.max_users ?? null),
      guests: userLimitToInput(loaded?.max_guests ?? null),
    }),
    [open, community?.id]
  );
  const [restoring, setRestoring] = useState(false);

  const update = useUpdateCommunityStorage({
    onSuccess: (row) => toast.success(t("communities.saved", { name: row.name })),
    onError: (err) => toast.error(getErrorMessage(err, "settings:communities.saveError")),
  });

  if (!community) return null;

  type Cap = keyof typeof form.values;
  const patch = (data: Parameters<typeof update.mutate>[0]["data"]) =>
    update.mutate({ communityId: community.id, data });
  // A cap is saved from its box, which then goes back to following the server.
  // A refused save leaves the old value in place, so that box goes back to it
  // rather than keeping a number nothing accepted.
  const commitCap = (
    data: Parameters<typeof update.mutate>[0]["data"],
    sent: typeof form.values,
    cap: Cap
  ) =>
    update.mutate(
      { communityId: community.id, data },
      { onSuccess: () => form.settle(sent), onError: () => form.reset({ [cap]: sent[cap] }) }
    );

  const commitStorage = () => {
    const sent = form.values;
    const { bytes, invalid } = parseGbInput(sent.storage);
    // A malformed entry snaps back to the persisted value rather than saving.
    if (invalid || bytes === (community.max_storage_bytes ?? null)) {
      form.reset({ storage: sent.storage });
      return;
    }
    commitCap({ max_storage_bytes: bytes }, sent, "storage");
  };

  const commitUsers = () => {
    const sent = form.values;
    const { limit, invalid } = parseUserLimitInput(sent.users);
    if (invalid || limit === (community.max_users ?? null)) {
      form.reset({ users: sent.users });
      return;
    }
    commitCap({ max_users: limit }, sent, "users");
  };

  const commitGuests = () => {
    const sent = form.values;
    const { limit, invalid } = parseGuestLimitInput(sent.guests);
    if (invalid || limit === (community.max_guests ?? null)) {
      form.reset({ guests: sent.guests });
      return;
    }
    commitCap({ max_guests: limit }, sent, "guests");
  };

  const options = community.auth_options ?? [];
  const toggleOption = (option: CommunityAuthOption, checked: boolean) =>
    patch({
      auth_options: checked ? [...options, option] : options.filter((held) => held !== option),
    });

  // A deleted community is on its way out. Its caps and entitlements are
  // settings for a community nobody can reach, so they are shown and frozen
  // rather than hidden — what it was configured as is worth seeing when you
  // are deciding whether to bring it back.
  const deleted = community.status === CommunityStatus.deleted;
  // What locks the plan's own controls: a community on its way out, or a plan
  // that billing sets.
  const planLocked = deleted || planIsBillings;
  const purgeDate = formatDate(community.purge_at);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {community.name}
            {community.tier_name ? <Badge variant="secondary">{community.tier_name}</Badge> : null}
          </SheetTitle>
          <SheetDescription>{t("communities.sheet.description")}</SheetDescription>
        </SheetHeader>

        <div className="space-y-6 py-6">
          {deleted ? (
            <Section title={t("communities.sheet.deleted")}>
              <div className="space-y-3 rounded-md border border-destructive/40 bg-destructive/5 p-4">
                <p className="text-sm">
                  {purgeDate
                    ? t("communities.restore.purgesOn", { date: purgeDate })
                    : t("communities.restore.purgesSoon")}
                </p>
                <p className="text-muted-foreground text-xs">{t("communities.restore.retained")}</p>
                <Button size="sm" onClick={() => setRestoring(true)}>
                  {t("communities.restore.open")}
                </Button>
              </div>
            </Section>
          ) : null}

          {planIsBillings && !deleted ? (
            <div className="space-y-3 rounded-md border bg-muted/40 p-4">
              <p className="text-sm">{t("communities.sheet.setInBilling")}</p>
              {/* The operator console changes a plan, which the row says this
                  reader may do; the support console is in the table. */}
              {billing?.operator_handoff &&
              opensBillingHere() &&
              community.allowed_actions.includes(CommunityAction.billing_operator) ? (
                <BillingConsoleButton community={community} console="operator" size="sm">
                  {t("communities.sheet.changeInBilling")}
                </BillingConsoleButton>
              ) : null}
            </div>
          ) : null}

          <Section title={t("communities.sheet.limits")}>
            <SettingRow
              label={t("communities.sheet.usersLabel")}
              help={t("communities.sheet.usersHelp")}
              htmlFor="community-max-users"
              control={
                <Input
                  id="community-max-users"
                  type="number"
                  min={1}
                  step={1}
                  inputMode="numeric"
                  className="w-32"
                  value={form.values.users}
                  onChange={(event) => form.set({ users: event.target.value })}
                  onBlur={commitUsers}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                  }}
                  placeholder={t("communities.unlimitedPlaceholder")}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.guestsLabel")}
              help={t("communities.sheet.guestsHelp")}
              htmlFor="community-max-guests"
              control={
                <Input
                  id="community-max-guests"
                  type="number"
                  min={0}
                  step={1}
                  inputMode="numeric"
                  className="w-32"
                  value={form.values.guests}
                  onChange={(event) => form.set({ guests: event.target.value })}
                  onBlur={commitGuests}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") event.currentTarget.blur();
                  }}
                  placeholder={t("communities.unlimitedPlaceholder")}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.storageLabel")}
              help={t("communities.sheet.storageHelp")}
              htmlFor="community-max-storage"
              control={
                <div className="relative w-32">
                  <Input
                    id="community-max-storage"
                    type="number"
                    min={0}
                    step="any"
                    inputMode="decimal"
                    className="pr-9"
                    value={form.values.storage}
                    onChange={(event) => form.set({ storage: event.target.value })}
                    onBlur={commitStorage}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") event.currentTarget.blur();
                    }}
                    placeholder={t("communities.unlimitedPlaceholder")}
                    disabled={update.isPending || planLocked}
                  />
                  <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground text-xs">
                    GB
                  </span>
                </div>
              }
            />
          </Section>

          {deleted ? null : <PluginSummarySections communityId={community.id} />}

          {/* Two separate grants. Either one can be given on its own. */}
          <Section title={t("communities.sheet.decidesForItself")}>
            <SettingRow
              label={t("communities.sheet.authOption.providers.label")}
              help={t("communities.sheet.authOption.providers.help")}
              htmlFor="community-auth-providers"
              control={
                <Switch
                  id="community-auth-providers"
                  checked={options.includes("providers")}
                  onCheckedChange={(checked) => toggleOption("providers", Boolean(checked))}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.authOption.restrictions.label")}
              help={t("communities.sheet.authOption.restrictions.help")}
              htmlFor="community-auth-restrictions"
              control={
                <Switch
                  id="community-auth-restrictions"
                  checked={options.includes("restrictions")}
                  onCheckedChange={(checked) => toggleOption("restrictions", Boolean(checked))}
                  disabled={update.isPending || planLocked}
                />
              }
            />
          </Section>

          <NarrowingsSection communityId={community.id} disabled={deleted} />

          <Section title={t("communities.sheet.features")}>
            <SettingRow
              label={t("communities.sheet.bannerLabel")}
              help={t("communities.sheet.bannerHelp")}
              htmlFor="community-banner-image"
              control={
                <Switch
                  id="community-banner-image"
                  checked={community.banner_image_enabled}
                  onCheckedChange={(checked) => patch({ banner_image_enabled: Boolean(checked) })}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.supportLabel")}
              help={
                supportBound || community.support_enabled
                  ? t("communities.sheet.supportHelp")
                  : t("communities.sheet.supportNeedsIntake")
              }
              htmlFor="community-support"
              control={
                <Switch
                  id="community-support"
                  checked={community.support_enabled}
                  onCheckedChange={(checked) => patch({ support_enabled: Boolean(checked) })}
                  // Switching it off stays available wherever it is on: a
                  // deployment that has stopped staffing help stops offering
                  // it, binding or no binding.
                  disabled={
                    update.isPending || planLocked || (!supportBound && !community.support_enabled)
                  }
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.aiConnectionsLabel")}
              help={t("communities.sheet.aiConnectionsHelp")}
              htmlFor="community-ai-connections"
              control={
                <Switch
                  id="community-ai-connections"
                  checked={community.ai_connections_open}
                  onCheckedChange={(checked) => patch({ ai_connections_open: Boolean(checked) })}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.pluginsLabel")}
              help={t("communities.sheet.pluginsHelp")}
              htmlFor="community-plugins"
              control={
                <Switch
                  id="community-plugins"
                  checked={community.plugins_open}
                  onCheckedChange={(checked) => patch({ plugins_open: Boolean(checked) })}
                  disabled={update.isPending || planLocked}
                />
              }
            />
            <SettingRow
              label={t("communities.sheet.customRolesLabel")}
              help={t("communities.sheet.customRolesHelp")}
              htmlFor="community-custom-roles"
              control={
                <Switch
                  id="community-custom-roles"
                  checked={community.custom_roles_open}
                  onCheckedChange={(checked) => patch({ custom_roles_open: Boolean(checked) })}
                  disabled={update.isPending || planLocked}
                />
              }
            />
          </Section>
        </div>
      </SheetContent>
      {restoring ? (
        <CommunityRestoreWizard
          community={community}
          open={restoring}
          onOpenChange={setRestoring}
        />
      ) : null}
    </Sheet>
  );
};

/**
 * What a community says its own arrivals look like, and whether anybody has
 * agreed.
 *
 * A community writes its own claim values and nothing in the app can tell
 * whether it holds the domain or tenant they name, so the answer is the
 * deployment's. Support answers through the case raised when they are
 * written; this is the same question where a deployment runs no intake, and
 * where an answer is withdrawn either way.
 */
const NarrowingsSection = ({
  communityId,
  disabled,
}: {
  communityId: number;
  disabled: boolean;
}) => {
  const { t } = useTranslation("settings");
  const narrowings = useCommunityNarrowings(communityId);
  const agree = useAgreeCommunityNarrowing(communityId, {
    onError: (err: unknown) =>
      toast.error(getErrorMessage(err, "settings:communities.sheet.narrowings.error")),
  });

  const rows = narrowings.data ?? [];
  if (narrowings.isLoading || rows.length === 0) return null;

  return (
    <Section title={t("communities.sheet.narrowings.title")}>
      <p className="text-muted-foreground text-sm">{t("communities.sheet.narrowings.help")}</p>
      <ul className="space-y-3">
        {rows.map((row) => (
          <li
            key={row.connection_id}
            className="flex items-start justify-between gap-3 rounded-md border px-4 py-3"
          >
            <div className="min-w-0 space-y-1">
              <p className="font-medium text-sm">
                {t("communities.sheet.narrowings.claims", {
                  provider: row.provider_display_name,
                  claim: row.claim,
                  values: row.claim_values.join(", "),
                })}
              </p>
              <p className="text-muted-foreground text-xs">
                {row.auto_join
                  ? t("communities.sheet.narrowings.joinsOnArrival")
                  : t("communities.sheet.narrowings.admitsOnly")}
              </p>
            </div>
            <Button
              size="sm"
              variant={row.agreed ? "outline" : "default"}
              disabled={disabled || agree.isPending}
              onClick={() =>
                agree.mutate({
                  connectionId: row.connection_id,
                  agreed: !row.agreed,
                })
              }
            >
              {row.agreed
                ? t("communities.sheet.narrowings.withdraw")
                : t("communities.sheet.narrowings.agree")}
            </Button>
          </li>
        ))}
      </ul>
    </Section>
  );
};

/**
 * Where the community stands with each installed plug-in that says — the
 * automation runs it has used, say — as its own Usage tab shows it, beside the
 * caps above. One read per plug-in, so one that does not answer holds up no
 * other.
 */
const PluginSummarySections = ({ communityId }: { communityId: number }) => {
  const { t } = useTranslation("settings");
  const { data, isError } = useListCommunityPluginSummaries(communityId);
  // A failed list is not an empty one: say so, rather than drawing nothing.
  if (isError) {
    return (
      <p className="text-muted-foreground text-sm">
        {t("communities.sheet.pluginSummariesUnavailable")}
      </p>
    );
  }
  return (
    <>
      {(data?.items ?? []).map((summary) => (
        <PluginSummarySection key={summary.plugin_id} communityId={communityId} summary={summary} />
      ))}
    </>
  );
};

const PluginSummarySection = ({
  communityId,
  summary,
}: {
  communityId: number;
  summary: PluginSummaryRead;
}) => {
  const { data, isError } = useReadCommunityPluginSummary(communityId, summary.plugin_id);
  return (
    <Section title={summary.name}>
      <div className="space-y-6 py-3">
        <PluginSummaryFigures summary={summary} data={data} isError={isError} />
      </div>
    </Section>
  );
};

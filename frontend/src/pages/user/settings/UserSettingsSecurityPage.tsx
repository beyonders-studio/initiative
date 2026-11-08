import { KeyRound, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useReadSecondFactor } from "@/api/generated/auth/auth";
import type { ApiKeyMetadata } from "@/api/generated/initiativeAPI.schemas";
import { useListMyApiKeys } from "@/api/generated/users/users";
import {
  isSubscription,
  NewSubscriptionLinkDialog,
  type SubscriptionKey,
} from "@/components/initiativeTools/events/CalendarSubscribeDialog";
import { HeldChangeNotice } from "@/components/settings/HeldChangeNotice";
import { PasskeysSection } from "@/components/settings/PasskeysSection";
import { PasswordSection } from "@/components/settings/PasswordSection";
import { SettingsSection } from "@/components/settings/SettingsSection";
import { SignedInSection } from "@/components/settings/SignedInSection";
import { TwoFactorSection } from "@/components/settings/TwoFactorSection";
import {
  ReportSecurityProblemButton,
  SecurityReportDialog,
  useSecurityReporting,
} from "@/components/tickets/ReportSecurityProblem";
import { useAppConfig } from "@/hooks/useAppConfig";
import { useAuth } from "@/hooks/useAuth";
import { useCommunities } from "@/hooks/useCommunities";
import { useCreateApiKey, useDeleteApiKey } from "@/hooks/useSecurity";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Checkbox } from "@/ui/checkbox";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { DateTimePicker } from "@/ui/date-time-picker";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";

const computeStatus = (key: ApiKeyMetadata) => {
  if (!key.is_active) {
    return { labelKey: "security.statusDisabled" as const, variant: "destructive" as const };
  }
  if (key.expires_at && new Date(key.expires_at).getTime() <= Date.now()) {
    return { labelKey: "security.statusExpired" as const, variant: "secondary" as const };
  }
  return null;
};

/**
 * Making an API key: the form, then the secret, which is shown once.
 */
const NewApiKeyDialog = ({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) => {
  const { t } = useTranslation(["settings", "common"]);
  const { communities } = useCommunities();
  const [name, setName] = useState("");
  const [expiresAtInput, setExpiresAtInput] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [communityId, setCommunityId] = useState<string>("all");
  const [secret, setSecret] = useState<string | null>(null);

  const close = () => {
    onOpenChange(false);
    setName("");
    setExpiresAtInput("");
    setReadOnly(false);
    setCommunityId("all");
    setSecret(null);
  };

  const createKey = useCreateApiKey({
    onSuccess: (data) => setSecret(data.secret),
    onError: () => toast.error(t("security.createError")),
  });

  const handleCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      toast.error(t("security.nameRequired"));
      return;
    }
    const payload: {
      name: string;
      expires_at?: string | null;
      read_only?: boolean;
      community_id?: number | null;
    } = { name: trimmedName, read_only: readOnly };
    if (expiresAtInput) {
      const parsed = new Date(expiresAtInput);
      if (!Number.isNaN(parsed.getTime())) {
        payload.expires_at = parsed.toISOString();
      }
    }
    if (communityId !== "all") {
      payload.community_id = Number(communityId);
    }
    createKey.mutate(payload);
  };

  const copySecret = () => {
    if (!secret || !navigator?.clipboard) {
      return;
    }
    void navigator.clipboard.writeText(secret).then(() => {
      toast.success(t("security.keyCopied"));
    });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent>
        {secret ? (
          <>
            <DialogHeader>
              <DialogTitle>{t("security.newKeyTitle")}</DialogTitle>
              <DialogDescription>{t("security.newKeyDescription")}</DialogDescription>
            </DialogHeader>
            <code className="block break-all rounded-md border bg-muted px-3 py-2 font-mono text-sm">
              {secret}
            </code>
            <DialogFooter className="gap-2">
              <Button type="button" variant="outline" onClick={copySecret}>
                {t("security.copy")}
              </Button>
              <Button type="button" onClick={close}>
                {t("common:done")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={handleCreate} className="space-y-4">
            <DialogHeader>
              <DialogTitle>{t("security.generateTitle")}</DialogTitle>
            </DialogHeader>
            <div className="space-y-2">
              <Label htmlFor="api-key-name">{t("security.keyNameLabel")}</Label>
              <Input
                id="api-key-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("security.keyNamePlaceholder")}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="api-key-community">{t("security.communityLabel")}</Label>
              <Select value={communityId} onValueChange={setCommunityId}>
                <SelectTrigger id="api-key-community">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{t("security.communityAllCommunities")}</SelectItem>
                  {communities
                    .filter((community) => community.can.use_api)
                    .map((community) => (
                      <SelectItem key={community.id} value={String(community.id)}>
                        {community.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <p className="text-muted-foreground text-xs">{t("security.communityHelp")}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="api-key-expiration">{t("security.expirationLabel")}</Label>
              <DateTimePicker
                id="api-key-expiration"
                value={expiresAtInput}
                onChange={setExpiresAtInput}
                placeholder={t("security.neverExpires")}
                calendarProps={{
                  hidden: {
                    before: new Date(),
                  },
                }}
              />
            </div>
            <div className="flex items-start gap-2">
              <Checkbox
                id="api-key-read-only"
                checked={readOnly}
                onCheckedChange={(checked) => setReadOnly(checked === true)}
                className="mt-0.5"
              />
              <div className="space-y-1">
                <Label htmlFor="api-key-read-only">{t("security.readOnlyLabel")}</Label>
                <p className="text-muted-foreground text-xs">{t("security.readOnlyHelp")}</p>
              </div>
            </div>
            <DialogFooter
              submitLabel={t("security.generateButton")}
              pendingLabel={t("security.generating")}
              pending={createKey.isPending}
            />
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
};

export const UserSettingsSecurityPage = () => {
  const { t } = useTranslation(["settings", "common", "intake", "calendars"]);
  const [creating, setCreating] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ApiKeyMetadata | null>(null);
  const [relinkTarget, setRelinkTarget] = useState<SubscriptionKey | null>(null);
  const [reporting, setReporting] = useState(false);
  const securityReporting = useSecurityReporting();
  const { user, refreshUser } = useAuth();
  // A way in this deployment does not offer is left off the page.
  const { passkeyLoginEnabled } = useAppConfig();
  // An account with no password keeps its recovery codes in the two-factor
  // section, so that section stays for it even where authenticators are off.
  const secondFactor = useReadSecondFactor();
  const showTwoFactor =
    (secondFactor.data?.offered ?? true) || (secondFactor.data?.passwordless ?? false);

  const { communities } = useCommunities();
  const communityName = (id: number) =>
    communities.find((community) => community.id === id)?.name ?? String(id);

  const apiKeysQuery = useListMyApiKeys();
  const apiKeys = apiKeysQuery.data?.keys ?? [];

  const deleteKey = useDeleteApiKey({
    onSuccess: () => toast.success(t("security.deleteSuccess")),
    onError: () => toast.error(t("security.deleteError")),
    onSettled: () => setDeleteTarget(null),
  });

  return (
    <div className="space-y-6">
      <HeldChangeNotice />
      {user ? <PasswordSection user={user} refreshUser={refreshUser} /> : null}

      {passkeyLoginEnabled ? (
        <SettingsSection title={t("passkeys.title")} description={t("passkeys.description")}>
          <PasskeysSection />
        </SettingsSection>
      ) : null}

      {showTwoFactor ? (
        <SettingsSection title={t("twoFactor.title")} description={t("twoFactor.description")}>
          <TwoFactorSection />
        </SettingsSection>
      ) : null}

      <SignedInSection />

      <SettingsSection
        title={t("security.apiKeysTitle")}
        description={t("security.apiKeysDescription")}
        action={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" />
            {t("security.newKeyButton")}
          </Button>
        }
      >
        {apiKeysQuery.isLoading ? (
          <p className="text-muted-foreground text-sm">{t("security.loadingKeys")}</p>
        ) : apiKeysQuery.isError ? (
          <p className="text-destructive text-sm">{t("security.keysError")}</p>
        ) : apiKeys.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("security.noKeys")}</p>
        ) : (
          <ul className="space-y-3">
            {apiKeys.map((key) => {
              const status = computeStatus(key);
              const detail = [
                `${key.token_prefix}…`,
                t("security.keyCreated", { date: formatDateTime(key.created_at) }),
                key.last_used_at
                  ? t("security.keyLastUsed", { date: formatDateTime(key.last_used_at) })
                  : t("security.keyNeverUsed"),
                key.expires_at
                  ? t("security.keyExpires", { date: formatDateTime(key.expires_at) })
                  : null,
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <li
                  key={key.id}
                  className="flex items-center justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-muted">
                      <KeyRound className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2 font-medium">
                        {key.name}
                        {status ? (
                          <Badge variant={status.variant}>{t(status.labelKey)}</Badge>
                        ) : null}
                        {key.read_only ? (
                          <Badge variant="secondary">{t("security.scopeReadOnly")}</Badge>
                        ) : null}
                        {key.community_id != null ? (
                          <Badge variant="outline">
                            {t("security.scopeCommunity", {
                              community: communityName(key.community_id),
                            })}
                          </Badge>
                        ) : null}
                        {key.resource_type != null ? (
                          <Badge variant="outline">{t("security.scopeSubscription")}</Badge>
                        ) : null}
                        {!key.read_only && key.community_id == null ? (
                          <Badge variant="outline">{t("security.scopeFull")}</Badge>
                        ) : null}
                      </p>
                      <p className="text-muted-foreground text-sm">{detail}</p>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap justify-end gap-2">
                    {isSubscription(key) ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => setRelinkTarget(key)}
                      >
                        {t("calendars:subscribe.getNewLink")}
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setDeleteTarget(key)}
                    >
                      {t("security.deleteButton")}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </SettingsSection>

      <NewApiKeyDialog open={creating} onOpenChange={setCreating} />
      {relinkTarget ? (
        <NewSubscriptionLinkDialog apiKey={relinkTarget} onClose={() => setRelinkTarget(null)} />
      ) : null}

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title={t("security.deleteDialogTitle")}
        description={t("security.deleteDialogDescription", { name: deleteTarget?.name ?? "" })}
        confirmLabel={t("security.deleteButton")}
        loadingLabel={t("security.deleting")}
        isLoading={deleteKey.isPending}
        destructive
        onConfirm={() => {
          if (deleteTarget) deleteKey.mutate(deleteTarget.id);
        }}
      />

      {/* Where this server takes them: something wrong with it, or with an
          account that isn't behaving like its owner. */}
      {securityReporting.form || securityReporting.contact ? (
        <SettingsSection
          title={t("intake:security.cardTitle")}
          description={t("intake:security.cardDescription")}
          action={<ReportSecurityProblemButton onOpen={() => setReporting(true)} />}
        />
      ) : null}
      <SecurityReportDialog open={reporting} onOpenChange={setReporting} />
    </div>
  );
};

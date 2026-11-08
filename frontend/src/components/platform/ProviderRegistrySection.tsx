import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  AuthProviderCreate,
  AuthProviderOwnerRead,
  AuthProviderProbeResult,
  AuthProviderUpdate,
} from "@/api/generated/initiativeAPI.schemas";
import { ProviderMark } from "@/components/auth/ProviderMark";
import { ConnectProviderWizard, ProbeReport } from "@/components/platform/ConnectProviderWizard";
import { getErrorMessage, messageForCode } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";
import { ConfirmDialog } from "@/ui/confirm-dialog";
import { CopyButton } from "@/ui/copy-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { ListSkeleton, SkeletonRegion } from "@/ui/page-skeletons";
import { Switch } from "@/ui/switch";

// The mutation surface the section needs — satisfied structurally by the
// React Query mutation objects the wrappers' domain hooks return, so the
// operator and community registries plug in without sharing hook signatures.
interface RegistryMutation<TVariables, TResult = unknown> {
  mutate: (
    variables: TVariables,
    options?: { onSuccess?: (data: TResult) => void; onError?: (error: unknown) => void }
  ) => void;
  isPending: boolean;
  /** Which row a shared mutation is currently busy with. */
  variables?: TVariables;
}

export interface ProviderRegistrySectionProps {
  title: string;
  description: string;
  dialogDescription: string;
  providers: AuthProviderOwnerRead[] | undefined;
  isLoading: boolean;
  createProvider: RegistryMutation<AuthProviderCreate>;
  updateProvider: RegistryMutation<{ providerId: number; data: AuthProviderUpdate }>;
  deleteProvider: RegistryMutation<number>;
  testProvider: RegistryMutation<number, AuthProviderProbeResult>;
  discoverIssuer: RegistryMutation<{ issuer: string }, AuthProviderProbeResult>;
}

/**
 * One login-provider registry as a settings card: list, create/edit dialog
 * with presets, write-only secret handling, and delete confirmation. The
 * operator registry (platform settings) and each community's registry (community
 * settings, per-community auth) both render through this — only the gates and
 * endpoints differ, supplied by the wrapper's hooks.
 */
export const ProviderRegistrySection = ({
  title,
  description,
  dialogDescription,
  providers,
  isLoading,
  createProvider,
  updateProvider,
  deleteProvider,
  testProvider,
  discoverIssuer,
}: ProviderRegistrySectionProps) => {
  const { t } = useTranslation("settings");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<AuthProviderOwnerRead | null>(null);
  const [deleting, setDeleting] = useState<AuthProviderOwnerRead | null>(null);

  const openEdit = (provider: AuthProviderOwnerRead) => {
    setEditing(provider);
    setDialogOpen(true);
  };

  /** Check a saved provider, against the address on the row. */
  const test = (provider: AuthProviderOwnerRead) => {
    testProvider.mutate(provider.id, {
      onSuccess: (result) => {
        if (result.ok) {
          toast.success(t("authProviders.probe.reachable"));
          return;
        }
        toast.error(messageForCode(result.error_code, "settings:authProviders.probe.failed"));
      },
      onError: (error) =>
        toast.error(getErrorMessage(error, "settings:authProviders.probe.failed")),
    });
  };

  const rows = providers ?? [];

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4 space-y-0">
        <div>
          <CardTitle>{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </div>
        <Button type="button" onClick={() => setWizardOpen(true)}>
          {t("authProviders.addProvider")}
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <SkeletonRegion>
            <ListSkeleton rows={3} />
          </SkeletonRegion>
        ) : rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("authProviders.empty")}</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {rows.map((provider) => (
              <li key={provider.id} className="flex items-center justify-between gap-4 px-3 py-3">
                <div className="flex min-w-0 items-start gap-3">
                  <ProviderMark icon={provider.icon} className="mt-0.5" />
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{provider.display_name}</span>
                      <code className="rounded bg-muted px-1 py-0.5 text-xs">{provider.slug}</code>
                      {!provider.enabled && (
                        <Badge variant="outline">{t("authProviders.disabledBadge")}</Badge>
                      )}
                    </div>
                    <p className="truncate text-muted-foreground text-sm">{provider.issuer}</p>
                    {/* The address this provider's IdP has to send the browser
                        back to. It follows the slug, and a slug never changes,
                        so it is good for as long as the provider is. */}
                    <div className="mt-1 flex items-center gap-1 text-muted-foreground text-xs">
                      <span className="shrink-0">{t("authProviders.callbackLabel")}</span>
                      <code className="min-w-0 truncate rounded bg-muted px-1 py-0.5">
                        {provider.callback_url}
                      </code>
                      <CopyButton
                        value={provider.callback_url}
                        variant="ghost"
                        className="h-6 w-6 p-0"
                        copiedMessage={t("authProviders.callbackCopied")}
                      />
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => test(provider)}
                    disabled={testProvider.isPending}
                    pending={testProvider.isPending && testProvider.variables === provider.id}
                  >
                    {testProvider.isPending && testProvider.variables === provider.id
                      ? t("authProviders.testing")
                      : t("authProviders.test")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => openEdit(provider)}
                  >
                    {t("authProviders.edit")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-destructive"
                    onClick={() => setDeleting(provider)}
                  >
                    {t("authProviders.delete")}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          {editing ? (
            <ProviderEditForm
              provider={editing}
              dialogDescription={dialogDescription}
              updateProvider={updateProvider}
              discoverIssuer={discoverIssuer}
              onDone={() => setDialogOpen(false)}
            />
          ) : null}
        </DialogContent>
      </Dialog>

      <ConnectProviderWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        createProvider={createProvider}
        discoverIssuer={discoverIssuer}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("authProviders.deleteTitle", { name: deleting?.display_name ?? "" })}
        description={t("authProviders.deleteDescription")}
        confirmLabel={t("authProviders.delete")}
        destructive
        isLoading={deleteProvider.isPending}
        onConfirm={() => {
          if (deleting) {
            deleteProvider.mutate(deleting.id, {
              onSuccess: () => {
                toast.success(t("authProviders.deleted"));
                setDeleting(null);
              },
              onError: (error) =>
                toast.error(getErrorMessage(error, "settings:authProviders.deleteError")),
            });
          }
        }}
      />
    </Card>
  );
};

// Drawn only while the dialog is open, so each opening starts from the
// provider as it is saved, with no secret typed and no check shown.
const ProviderEditForm = ({
  provider,
  dialogDescription,
  updateProvider,
  discoverIssuer,
  onDone,
}: Pick<ProviderRegistrySectionProps, "dialogDescription" | "updateProvider" | "discoverIssuer"> & {
  provider: AuthProviderOwnerRead;
  onDone: () => void;
}) => {
  const { t } = useTranslation("settings");
  const [form, setForm] = useState({
    slug: provider.slug,
    display_name: provider.display_name,
    issuer: provider.issuer ?? "",
    client_id: provider.client_id ?? "",
    client_secret: "",
    scopes: provider.scopes ?? "",
    role_claim_path: provider.role_claim_path ?? "",
    allow_jit: provider.allow_jit,
    asserts_second_factor: provider.asserts_second_factor ?? false,
    enabled: provider.enabled,
  });
  const [probe, setProbe] = useState<AuthProviderProbeResult | null>(null);
  const [clearSecret, setClearSecret] = useState(false);

  /** Check the address in the form, without saving it. */
  const verify = () => {
    discoverIssuer.mutate(
      { issuer: form.issuer },
      {
        onSuccess: setProbe,
        onError: (error) =>
          toast.error(getErrorMessage(error, "settings:authProviders.verifyError")),
      }
    );
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateProvider.mutate(
      {
        providerId: provider.id,
        data: {
          display_name: form.display_name,
          issuer: form.issuer,
          client_id: form.client_id,
          scopes: form.scopes || null,
          role_claim_path: form.role_claim_path.trim() || null,
          allow_jit: form.allow_jit,
          asserts_second_factor: form.asserts_second_factor,
          enabled: form.enabled,
          // Write-only secret: absent keeps, empty string clears.
          ...(clearSecret
            ? { client_secret: "" }
            : form.client_secret
              ? { client_secret: form.client_secret }
              : {}),
        },
      },
      {
        onSuccess: () => {
          toast.success(t("authProviders.saved"));
          onDone();
        },
        onError: (error) => toast.error(getErrorMessage(error, "settings:authProviders.saveError")),
      }
    );
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("authProviders.editTitle")}</DialogTitle>
        <DialogDescription>{dialogDescription}</DialogDescription>
      </DialogHeader>
      <form className="space-y-4" onSubmit={handleSubmit}>
        {/* The one value that goes the other way, kept to hand for
                somebody who is re-registering this provider at its own end. */}
        <div className="space-y-2 rounded-md border bg-muted/40 p-3">
          <Label>{t("authProviders.callbackLabel")}</Label>
          <div className="flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1.5 text-xs">
              {provider.callback_url}
            </code>
            <CopyButton
              value={provider.callback_url}
              copiedMessage={t("authProviders.callbackCopied")}
            />
          </div>
        </div>
        <Field label={t("authProviders.slugLabel")} hint={t("authProviders.slugHelp")}>
          <Input value={form.slug} maxLength={64} disabled required />
        </Field>
        <Field label={t("authProviders.displayNameLabel")}>
          <Input
            value={form.display_name}
            onChange={(event) => setForm((prev) => ({ ...prev, display_name: event.target.value }))}
            required
          />
        </Field>
        <div className="space-y-2">
          <Label htmlFor="provider-issuer">{t("authProviders.issuerLabel")}</Label>
          <div className="flex items-center gap-2">
            <Input
              id="provider-issuer"
              type="url"
              value={form.issuer}
              onChange={(event) => {
                // A tick beside an address that has since been edited
                // would be vouching for something else.
                setProbe(null);
                setForm((prev) => ({ ...prev, issuer: event.target.value }));
              }}
              placeholder={t("authProviders.issuerPlaceholder")}
              required
            />
            <Button
              type="button"
              variant="outline"
              onClick={verify}
              disabled={!form.issuer.trim()}
              pending={discoverIssuer.isPending}
            >
              {discoverIssuer.isPending ? t("authProviders.verifying") : t("authProviders.verify")}
            </Button>
          </div>
          {probe ? <ProbeReport probe={probe} /> : null}
        </div>
        <Field label={t("authProviders.clientIdLabel")}>
          <Input
            value={form.client_id}
            onChange={(event) => setForm((prev) => ({ ...prev, client_id: event.target.value }))}
            required
          />
        </Field>
        <div className="space-y-2">
          <Label htmlFor="provider-client-secret">{t("authProviders.clientSecretLabel")}</Label>
          <Input
            id="provider-client-secret"
            type="password"
            value={form.client_secret}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, client_secret: event.target.value }))
            }
            placeholder={
              provider.secret_set
                ? t("authProviders.secretKeepPlaceholder")
                : t("authProviders.secretPlaceholder")
            }
            disabled={clearSecret}
          />
          {provider.secret_set && (
            <label className="flex items-center gap-2 text-muted-foreground text-xs">
              <input
                type="checkbox"
                checked={clearSecret}
                onChange={(event) => setClearSecret(event.target.checked)}
              />
              {t("authProviders.clearSecret")}
            </label>
          )}
        </div>
        <Field label={t("authProviders.scopesLabel")}>
          <Input
            value={form.scopes}
            onChange={(event) => setForm((prev) => ({ ...prev, scopes: event.target.value }))}
          />
        </Field>
        {/* Whose groups these are and how this provider spells them.
            Rules below read it, and each provider spells it its own
            way — Keycloak nests roles, Entra flattens them. */}
        <Field
          label={t("authProviders.claimPathLabel")}
          hint={t("authProviders.claimPathHelp")}
          className="space-y-1"
        >
          <Input
            value={form.role_claim_path}
            placeholder={t("authProviders.claimPathPlaceholder")}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, role_claim_path: event.target.value }))
            }
          />
        </Field>
        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
          <div>
            <Label htmlFor="provider-allow-jit" className="font-medium">
              {t("authProviders.allowJitLabel")}
            </Label>
            <p className="text-muted-foreground text-xs">{t("authProviders.allowJitHelp")}</p>
          </div>
          <Switch
            id="provider-allow-jit"
            checked={form.allow_jit}
            onCheckedChange={(checked) =>
              setForm((prev) => ({ ...prev, allow_jit: Boolean(checked) }))
            }
          />
        </div>
        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
          <div>
            <Label htmlFor="provider-asserts-factor" className="font-medium">
              {t("authProviders.assertsSecondFactorLabel")}
            </Label>
            <p className="text-muted-foreground text-xs">
              {t("authProviders.assertsSecondFactorHelp")}
            </p>
          </div>
          <Switch
            id="provider-asserts-factor"
            checked={form.asserts_second_factor}
            onCheckedChange={(checked) =>
              setForm((prev) => ({ ...prev, asserts_second_factor: Boolean(checked) }))
            }
          />
        </div>
        <div className="flex items-center justify-between rounded-md border bg-muted/40 px-3 py-2">
          <Label htmlFor="provider-enabled" className="font-medium">
            {t("authProviders.enabledLabel")}
          </Label>
          <Switch
            id="provider-enabled"
            checked={form.enabled}
            onCheckedChange={(checked) =>
              setForm((prev) => ({ ...prev, enabled: Boolean(checked) }))
            }
          />
        </div>
        <DialogFooter
          submitLabel={t("authProviders.save")}
          pendingLabel={t("authProviders.saving")}
          pending={updateProvider.isPending}
        />
      </form>
    </>
  );
};

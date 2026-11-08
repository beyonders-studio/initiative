import { browserSupportsWebAuthn, WebAuthnError } from "@simplewebauthn/browser";
import { KeyRound, Pencil, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getListPasskeysQueryKey,
  useBeginPasskeyRegistration,
  useFinishPasskeyRegistration,
  useListPasskeys,
  useRemovePasskey,
  useRenamePasskey,
} from "@/api/generated/auth/auth";
import type {
  PasskeyRead,
  PasskeyRegisterFinishCredential,
} from "@/api/generated/initiativeAPI.schemas";
import { useAnnounceHeld } from "@/hooks/useHeldChange";
import { useServer } from "@/hooks/useServer";
import { useWizard } from "@/hooks/useWizard";
import { getErrorMessage } from "@/lib/errorMessage";
import { formatDateTime } from "@/lib/formatDate";
import { toast } from "@/lib/mascotToast";
import { hasReservedSigil } from "@/lib/mentions";
import { createCredential } from "@/lib/passkeys";
import { queryClient } from "@/lib/queryClient";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
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
import { WizardDialog } from "@/ui/wizard-dialog";

/** The form, then the wait for the browser's own prompt. */
type AddStep = "details" | "prompting";

type PromptMessageKey =
  | "passkeys.cancelled"
  | "passkeys.alreadyRegistered"
  | "passkeys.siteMismatch"
  | "passkeys.browserError";

const PROMPT_MESSAGE_KEYS: Record<string, PromptMessageKey> = {
  NotAllowedError: "passkeys.cancelled",
  InvalidStateError: "passkeys.alreadyRegistered",
  // The browser will only make a passkey for the address the deployment is
  // configured under, so this one is for whoever runs the site to sort out.
  SecurityError: "passkeys.siteMismatch",
};

/**
 * Which line to show when the prompt ends without a credential.
 *
 * `createCredential` raises a {@link WebAuthnError} named after the browser's
 * own exception, or the app's refusal under the browser's name for it, and
 * anything else that lands in the same catch keeps whatever name it had; all
 * are read the same way, and a name with no line of its own gets the general
 * one.
 */
const promptMessageKey = (error: unknown): PromptMessageKey => {
  const name = error instanceof WebAuthnError || error instanceof Error ? error.name : "";
  return PROMPT_MESSAGE_KEYS[name] ?? "passkeys.browserError";
};

/**
 * The passkeys an account holds, on its own security page.
 *
 * Adding one is a conversation with the browser rather than a form: the server
 * hands over the options, the browser's prompt produces the credential, and
 * the server is told what came back. The name is typed here first and kept on
 * the form, so a prompt that ended in nothing can be tried again without
 * retyping it.
 *
 * In an app the prompt runs wherever `lib/passkeys` can run it: the app's own
 * plug-in, or the system browser on the deployment's page. Renaming and
 * removing are ordinary requests and work anywhere.
 */
export const PasskeysSection = () => {
  const { t } = useTranslation(["settings", "errors", "common"]);
  const announceHeld = useAnnounceHeld();
  const { isNativePlatform } = useServer();

  const list = useListPasskeys();
  const refresh = () => queryClient.invalidateQueries({ queryKey: getListPasskeysQueryKey() });

  const [addOpen, setAddOpen] = useState(false);
  const { step, go, back, reset } = useWizard<AddStep>("details");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [renameTarget, setRenameTarget] = useState<PasskeyRead | null>(null);
  const [renameName, setRenameName] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);

  const [removeTarget, setRemoveTarget] = useState<PasskeyRead | null>(null);
  const [removePassword, setRemovePassword] = useState("");
  const [removeError, setRemoveError] = useState<string | null>(null);

  const passkeys = list.data?.passkeys ?? [];
  // The server is what knows whether there is a password to re-check. Asking
  // is the safe guess while the answer is still on its way.
  const passwordRequired = list.data?.password_required ?? true;
  const limit = list.data?.limit ?? 0;
  const atLimit = limit > 0 && passkeys.length >= limit;
  // Whether the deployment itself can carry a passkey. Two answers, and either
  // one settles it: the server knows the address it is configured under, and
  // the page knows whether it is in a secure context — served over plain http
  // at anything but localhost, it is not, and no credential API exists to ask.
  //
  // On a phone the ceremony happens in the app's credential manager or the
  // system browser, so this webview's own context says nothing; only the
  // server's half speaks for it. The same
  // goes for what this browser can do, below.
  const siteUnsupported =
    list.data?.site_supported === false || (!isNativePlatform && !window.isSecureContext);
  // The deployment can stop offering passkeys. What an account already holds
  // stays where it is — it can still be renamed, and removed — but there is
  // nothing to add.
  const offered = list.data?.offered ?? true;
  // On a phone the ceremony happens outside this webview, so what it can do
  // says nothing about whether a passkey can be added.
  const unsupported = !isNativePlatform && !browserSupportsWebAuthn();

  const closeAdd = () => {
    setAddOpen(false);
    reset();
    setName("");
    setPassword("");
    setError(null);
  };

  const finish = useFinishPasskeyRegistration({
    mutation: {
      onSuccess: () => {
        toast.success(t("passkeys.added"));
        void refresh();
        closeAdd();
      },
      onError: (err) => {
        setError(getErrorMessage(err, "settings:passkeys.error"));
        back();
      },
    },
  });

  const begin = useBeginPasskeyRegistration({
    mutation: {
      onSuccess: async (data) => {
        setError(null);
        go("prompting");
        try {
          const credential = await createCredential(data.options);
          finish.mutate({
            data: {
              credential: credential as unknown as PasskeyRegisterFinishCredential,
              name: name.trim(),
            },
          });
        } catch (err) {
          setError(t(promptMessageKey(err)));
          back();
        }
      },
      onError: (err) => setError(getErrorMessage(err, "settings:passkeys.error")),
    },
  });

  const rename = useRenamePasskey({
    mutation: {
      onSuccess: () => {
        toast.success(t("passkeys.renamed"));
        void refresh();
        setRenameTarget(null);
      },
      onError: (err) => setRenameError(getErrorMessage(err, "settings:passkeys.error")),
    },
  });

  const remove = useRemovePasskey({
    mutation: {
      onSuccess: (result) => {
        if (result.held) announceHeld(result.held);
        else toast.success(t("passkeys.removed"));
        void refresh();
        setRemoveTarget(null);
        setRemovePassword("");
      },
      onError: (err) => setRemoveError(getErrorMessage(err, "settings:passkeys.error")),
    },
  });

  const openAdd = () => {
    reset();
    setName("");
    setPassword("");
    setError(null);
    setAddOpen(true);
  };

  const submitAdd = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    // The server holds names to the same rule and refuses this one before the
    // browser is asked for anything, so say it here rather than making a
    // credential nothing will accept. Same sentence either way.
    if (hasReservedSigil(trimmed)) {
      setError(t("errors:RESERVED_SIGIL_IN_NAME"));
      return;
    }
    // The name travels with both halves: the server needs it to refuse early,
    // and again to store what the browser sends back.
    begin.mutate({ data: { current_password: password || null, name: trimmed } });
  };

  const submitRename = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!renameTarget) return;
    rename.mutate({ passkeyId: renameTarget.id, data: { name: renameName.trim() } });
  };

  const submitRemove = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!removeTarget) return;
    remove.mutate({
      passkeyId: removeTarget.id,
      data: { current_password: removePassword || null },
    });
  };

  // A full set is the first thing to say, on a phone as much as anywhere:
  // sending somebody to a browser to be told there is no room would be rude.
  // Then what the deployment itself can carry, which no browser can put right,
  // and only after that what this particular browser can do.
  const addNote = !offered
    ? t("passkeys.notOffered")
    : atLimit
      ? t("passkeys.limitReached", { limit })
      : siteUnsupported
        ? t("passkeys.siteUnsupported")
        : unsupported
          ? t("passkeys.unsupported")
          : null;

  return (
    <div className="space-y-4">
      {list.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("passkeys.loading")}</p>
      ) : list.isError ? (
        <p className="text-destructive text-sm">{t("passkeys.listError")}</p>
      ) : (
        <div className="space-y-4">
          {passkeys.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-6 text-center text-muted-foreground">
              <KeyRound className="h-10 w-10 opacity-50" />
              <div>
                <p className="font-medium">{t("passkeys.empty")}</p>
                <p className="text-sm">{t("passkeys.emptyHint")}</p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {passkeys.map((passkey) => (
                <div
                  key={passkey.id}
                  className="flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-medium">{passkey.name}</p>
                      {passkey.backed_up ? (
                        <Badge variant="secondary">{t("passkeys.synced")}</Badge>
                      ) : null}
                    </div>
                    <p className="text-muted-foreground text-sm">
                      {t("passkeys.addedOn", { date: formatDateTime(passkey.created_at) })}
                    </p>
                    <p className="text-muted-foreground text-sm">
                      {passkey.last_used_at
                        ? t("passkeys.lastUsed", { date: formatDateTime(passkey.last_used_at) })
                        : t("passkeys.neverUsed")}
                    </p>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setRenameError(null);
                        setRenameName(passkey.name);
                        setRenameTarget(passkey);
                      }}
                    >
                      <Pencil className="h-4 w-4" />
                      {t("passkeys.rename")}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setRemoveError(null);
                        setRemovePassword("");
                        setRemoveTarget(passkey);
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                      {t("passkeys.remove")}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {addNote ? <p className="text-muted-foreground text-sm">{addNote}</p> : null}

          {offered ? (
            <Button
              type="button"
              onClick={openAdd}
              disabled={atLimit || siteUnsupported || unsupported}
            >
              {t("passkeys.add")}
            </Button>
          ) : null}
        </div>
      )}

      <WizardDialog
        open={addOpen}
        onOpenChange={(open) => (open ? setAddOpen(true) : closeAdd())}
        title={t("passkeys.addTitle")}
        description={step === "details" ? t("passkeys.addPrompt") : t("passkeys.prompting")}
        progress={{ current: step === "details" ? 1 : 2, total: 2 }}
      >
        {step === "details" ? (
          <form className="space-y-4" onSubmit={submitAdd}>
            <div className="space-y-2">
              <Label htmlFor="passkey-name">{t("passkeys.nameLabel")}</Label>
              <Input
                id="passkey-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder={t("passkeys.namePlaceholder")}
                maxLength={64}
                required
              />
            </div>
            {passwordRequired ? (
              <div className="space-y-2">
                <Label htmlFor="passkey-password">{t("passkeys.passwordLabel")}</Label>
                <Input
                  id="passkey-password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
            ) : null}
            {error ? <p className="text-destructive text-sm">{error}</p> : null}
            <DialogFooter>
              <Button type="submit" disabled={begin.isPending || !name.trim()}>
                {t("passkeys.continue")}
              </Button>
            </DialogFooter>
          </form>
        ) : null}

        {step === "prompting" ? (
          <p className="py-4 text-center text-muted-foreground text-sm">
            {t("passkeys.promptingHint")}
          </p>
        ) : null}
      </WizardDialog>

      <Dialog
        open={renameTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("passkeys.renameTitle")}</DialogTitle>
            <DialogDescription>{t("passkeys.renamePrompt")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitRename}>
            <div className="space-y-2">
              <Label htmlFor="passkey-rename">{t("passkeys.nameLabel")}</Label>
              <Input
                id="passkey-rename"
                value={renameName}
                onChange={(event) => setRenameName(event.target.value)}
                maxLength={64}
                required
              />
            </div>
            {renameError ? <p className="text-destructive text-sm">{renameError}</p> : null}
            <DialogFooter>
              <Button type="submit" disabled={rename.isPending || !renameName.trim()}>
                {t("passkeys.save")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        open={removeTarget !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("passkeys.removeTitle")}</DialogTitle>
            <DialogDescription>
              {t("passkeys.removeConfirm", { name: removeTarget?.name ?? "" })}
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitRemove}>
            {passwordRequired ? (
              <div className="space-y-2">
                <Label htmlFor="passkey-remove-password">{t("passkeys.passwordLabel")}</Label>
                <Input
                  id="passkey-remove-password"
                  type="password"
                  autoComplete="current-password"
                  value={removePassword}
                  onChange={(event) => setRemovePassword(event.target.value)}
                  required
                />
              </div>
            ) : null}
            {removeError ? <p className="text-destructive text-sm">{removeError}</p> : null}
            <DialogFooter
              submitLabel={t("passkeys.remove")}
              pending={remove.isPending}
              destructive
            />
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

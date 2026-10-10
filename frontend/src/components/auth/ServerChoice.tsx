import { Capacitor } from "@capacitor/core";
import { Check, ChevronDown } from "lucide-react";
import { type FormEvent, type ReactNode, useState } from "react";
import { Trans, useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/useAuth";
import { useIsDemoServer } from "@/hooks/useDemoCopy";
import { normalizeServerUrl, useServer } from "@/hooks/useServer";
import { getSelfHostedAddress, setSelfHostedAddress } from "@/lib/serverStorage";
import { clearStart } from "@/lib/startFlow";
import { cn } from "@/lib/utils";
import AppEnvironment from "@/plugins/appEnvironment";

/**
 * The kind of server a sign-in goes to, where it cannot be changed: in a
 * browser, which is on its server already, and on the app's pages that a
 * link opened for one server.
 */
export const ServerChip = () => {
  const { t } = useTranslation("auth");
  const kind = useIsDemoServer() ? t("server.demo") : t("server.selfHosted");
  return (
    <Badge className="hover:bg-primary" aria-label={`${t("server.label")}: ${kind}`}>
      {kind}
    </Badge>
  );
};

/**
 * Where signing in or up goes, inside its card. In the app a self-hosted
 * server takes an address, which the app keeps for next time. A browser is
 * on its server already, so there it is the chip.
 */
export const ServerPicker = ({ className }: { className?: string }) => {
  const { isNativePlatform } = useServer();
  return isNativePlatform ? <AppServerPicker className={className} /> : <ServerChip />;
};

const AppServerPicker = ({ className }: { className?: string }) => {
  const { t } = useTranslation("auth");
  // Initiative Cloud is not open yet, so self-hosted is the only choice.
  const [where, setWhere] = useState("selfHosted");

  return (
    <div className={cn("space-y-2", className)}>
      <Select value={where} onValueChange={setWhere}>
        <SelectTrigger aria-label={t("server.label")} className="h-8 w-auto gap-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="cloud" disabled>
            {t("server.cloud")} · {t("server.cloudSoon")}
          </SelectItem>
          <SelectItem value="selfHosted">{t("server.selfHosted")}</SelectItem>
        </SelectContent>
      </Select>
      {where === "selfHosted" ? <ServerAddressForm /> : null}
    </div>
  );
};

/** The host a sign-in goes to, port included: what a person would type. */
const hostOf = (origin: string | null): string | null => {
  if (!origin) return null;
  try {
    return new URL(origin).host;
  } catch {
    return null;
  }
};

/**
 * Where a sign-in goes, under the sign-in card's title. A browser is on its
 * server already, so there it is only the chip; in the app it is "Sign in to
 * <server>" with the server as a small menu, and choosing your own server
 * opens its address beneath.
 */
export const ServerSubtitle = () => {
  const { t } = useTranslation("auth");
  const { isNativePlatform, getServerOrigin } = useServer();
  const host = hostOf(getServerOrigin());
  const demo = useIsDemoServer();
  const [editing, setEditing] = useState(false);

  if (!isNativePlatform) return <ServerChip />;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <p>
          <Trans
            t={t}
            i18nKey="login.signInTo"
            values={{ server: demo ? t("server.demo") : (host ?? t("server.selfHosted")) }}
            components={{
              server: <ServerMenu onChooseOwn={() => setEditing(true)} />,
            }}
          />
        </p>
        {host || demo ? <ServerChip /> : null}
      </div>
      {editing ? <ServerAddressForm onConnected={() => setEditing(false)} /> : null}
    </div>
  );
};

const ServerMenu = ({
  children,
  onChooseOwn,
}: {
  children?: ReactNode;
  onChooseOwn: () => void;
}) => {
  const { t } = useTranslation("auth");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("server.label")}
        className="inline-flex items-center gap-0.5 rounded-sm font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {children}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem disabled>
          <span className="flex-1">{t("server.cloud")}</span>
          <span className="text-muted-foreground text-xs">{t("server.cloudSoon")}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onChooseOwn}>
          <span className="flex-1">{t("server.ownServer")}</span>
          <Check aria-hidden />
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

/** A self-hosted server's address, which the app keeps for next time. */
const ServerAddressForm = ({ onConnected }: { onConnected?: () => void }) => {
  const { t } = useTranslation("auth");
  const { serverUrl, setServerUrl, testServerConnection, getServerOrigin } = useServer();
  const { user, logout } = useAuth();
  const [address, setAddress] = useState(() => getSelfHostedAddress() ?? getServerOrigin() ?? "");
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const trimmed = address.trim();
  const isCurrent =
    serverUrl !== null && trimmed !== "" && normalizeServerUrl(trimmed) === serverUrl;

  // A phone app that cannot reach plain-HTTP servers says so when an http:// address fails.
  // iOS never can; an Android release build cannot, while a debug build can.
  const failure = async (fallback: string) => {
    if (!/^http:\/\//i.test(trimmed)) return fallback;
    const platform = Capacitor.getPlatform();
    if (platform === "ios") return t("server.httpsOnly");
    if (platform !== "android") return fallback;
    const { cleartextPermitted } = await AppEnvironment.get().catch(() => ({
      cleartextPermitted: undefined,
    }));
    return cleartextPermitted === false ? t("server.httpsOnly") : fallback;
  };

  const handleConnect = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!trimmed || isCurrent) return;
    setConnecting(true);
    setError(null);
    try {
      const result = await testServerConnection(trimmed);
      if (!result.valid) {
        setError(await failure(result.error ?? t("server.connectError")));
        return;
      }
      // A sign-up begun on one server stays there, and leaving a server signs
      // out of it. The draft goes first: if it cannot, nothing has changed.
      await clearStart();
      if (user) await logout();
      setSelfHostedAddress(trimmed);
      await setServerUrl(trimmed);
      onConnected?.();
    } catch {
      setError(await failure(t("server.connectError")));
    } finally {
      setConnecting(false);
    }
  };

  return (
    <form className="space-y-2" onSubmit={handleConnect}>
      <div className="flex gap-2">
        <Input
          aria-label={t("server.addressLabel")}
          type="url"
          placeholder={t("server.addressPlaceholder")}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          required
        />
        <Button type="submit" variant="outline" disabled={connecting || isCurrent}>
          {isCurrent ? t("server.connected") : t("server.connect")}
        </Button>
      </div>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </form>
  );
};

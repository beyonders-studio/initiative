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
import {
  CLOUD_ORIGIN,
  CLOUD_SERVER_URL,
  getSelfHostedAddress,
  setSelfHostedAddress,
} from "@/lib/serverStorage";
import { clearStart } from "@/lib/startFlow";
import { cn } from "@/lib/utils";
import AppEnvironment from "@/plugins/appEnvironment";

/** Whether the server a sign-in goes to is Initiative Cloud. */
const useIsCloudServer = (): boolean => useServer().getServerOrigin() === CLOUD_ORIGIN;

/**
 * Leaving a server: a sign-up begun on it stays there, and leaving signs out
 * of it. The draft goes first: if it cannot, nothing has changed.
 */
const useLeaveServer = () => {
  const { user, logout } = useAuth();
  return async () => {
    await clearStart();
    if (user) await logout();
  };
};

/** Moves the app to Initiative Cloud, signed out of the server it leaves. */
const useSwitchToCloud = () => {
  const { t } = useTranslation("auth");
  const { setServerUrl } = useServer();
  const leaveServer = useLeaveServer();
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState(false);
  const switchToCloud = async () => {
    setError(null);
    setSwitching(true);
    try {
      await leaveServer();
      await setServerUrl(CLOUD_SERVER_URL);
      return true;
    } catch {
      setError(t("server.connectError"));
      return false;
    } finally {
      setSwitching(false);
    }
  };
  return { switchToCloud, switching, error };
};

/**
 * The kind of server a sign-in goes to, where it cannot be changed: in a
 * browser, which is on its server already, and on the app's pages that a
 * link opened for one server.
 */
export const ServerChip = () => {
  const { t } = useTranslation("auth");
  const demo = useIsDemoServer();
  const cloud = useIsCloudServer();
  const kind = demo ? t("server.demo") : cloud ? t("server.cloud") : t("server.selfHosted");
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
  const { serverUrl } = useServer();
  const cloud = useIsCloudServer();
  // An app with no server of its own starts on Initiative Cloud.
  const [where, setWhere] = useState(serverUrl === null || cloud ? "cloud" : "selfHosted");
  const { switchToCloud, switching, error } = useSwitchToCloud();
  // The choice holds while a server is being reached, so the one shown is the
  // one the app ends up on.
  const [connecting, setConnecting] = useState(false);

  const choose = async (next: string) => {
    if (next === "cloud" && !cloud && !(await switchToCloud())) return;
    setWhere(next);
  };

  return (
    <div className={cn("space-y-2", className)}>
      <Select value={where} onValueChange={choose} disabled={connecting || switching}>
        <SelectTrigger aria-label={t("server.label")} className="h-8 w-auto gap-2">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="cloud">{t("server.cloud")}</SelectItem>
          <SelectItem value="selfHosted">{t("server.selfHosted")}</SelectItem>
        </SelectContent>
      </Select>
      {where === "selfHosted" ? <ServerAddressForm onBusyChange={setConnecting} /> : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
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
 * <server>" with the server as a small menu: Initiative Cloud, or your own
 * server, which opens its address beneath.
 */
export const ServerSubtitle = () => {
  const { t } = useTranslation("auth");
  const { isNativePlatform, getServerOrigin } = useServer();
  const host = hostOf(getServerOrigin());
  const demo = useIsDemoServer();
  const cloud = useIsCloudServer();
  const [editing, setEditing] = useState(false);
  const { switchToCloud, switching, error } = useSwitchToCloud();
  const [connecting, setConnecting] = useState(false);

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
              server: (
                <ServerMenu
                  cloud={cloud}
                  disabled={connecting || switching}
                  onChooseCloud={async () => {
                    setEditing(false);
                    if (!cloud) await switchToCloud();
                  }}
                  onChooseOwn={() => setEditing(true)}
                />
              ),
            }}
          />
        </p>
        {host || demo ? <ServerChip /> : null}
      </div>
      {editing ? (
        <ServerAddressForm onConnected={() => setEditing(false)} onBusyChange={setConnecting} />
      ) : null}
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </div>
  );
};

const ServerMenu = ({
  children,
  cloud,
  disabled,
  onChooseCloud,
  onChooseOwn,
}: {
  children?: ReactNode;
  cloud: boolean;
  disabled?: boolean;
  onChooseCloud: () => void;
  onChooseOwn: () => void;
}) => {
  const { t } = useTranslation("auth");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("server.label")}
        disabled={disabled}
        className="inline-flex items-center gap-0.5 rounded-sm font-medium text-foreground underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {children}
        <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuItem onSelect={onChooseCloud}>
          <span className="flex-1">{t("server.cloud")}</span>
          {cloud ? <Check aria-hidden /> : null}
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={onChooseOwn}>
          <span className="flex-1">{t("server.ownServer")}</span>
          {cloud ? null : <Check aria-hidden />}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
};

/** A self-hosted server's address, which the app keeps for next time. */
const ServerAddressForm = ({
  onConnected,
  onBusyChange,
}: {
  onConnected?: () => void;
  /** Whether a connection is under way, for a choice that must hold meanwhile. */
  onBusyChange?: (busy: boolean) => void;
}) => {
  const { t } = useTranslation("auth");
  const { serverUrl, setServerUrl, testServerConnection, getServerOrigin } = useServer();
  const leaveServer = useLeaveServer();
  // Initiative Cloud's address is not one to fill in for your own server.
  const [address, setAddress] = useState(() => {
    const origin = getServerOrigin();
    return getSelfHostedAddress() ?? (origin === CLOUD_ORIGIN ? null : origin) ?? "";
  });
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
    onBusyChange?.(true);
    setError(null);
    try {
      const result = await testServerConnection(trimmed);
      if (!result.valid) {
        setError(await failure(result.error ?? t("server.connectError")));
        return;
      }
      await leaveServer();
      setSelfHostedAddress(trimmed);
      await setServerUrl(trimmed);
      onConnected?.();
    } catch {
      setError(await failure(t("server.connectError")));
    } finally {
      setConnecting(false);
      onBusyChange?.(false);
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

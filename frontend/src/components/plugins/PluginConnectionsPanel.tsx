/**
 * A plug-in's settings, grouped by connection.
 *
 * The grouping is the point rather than a layout choice. A plug-in does not have
 * "settings" — it has connections, each of which reaches a different system
 * with different permissions, and each of which is supplied by a different
 * person. Showing them as one flat form would hide the distinction that
 * matters:
 *
 * - A **community connection** is one credential the whole community uses. A community
 *   admin fills it in; everyone else sees whether it is set, because whether an
 *   plug-in can do its job is not a secret. Some are typed and some are not: where
 *   the vendor authorizes an organization through a page of its own, the admin
 *   is sent there and Initiative records what came back, so the form has
 *   nothing in it and a button instead.
 * - A **personal connection** is each member's own account at a vendor that
 *   authorizes people rather than organizations. Every member sees their own
 *   state and only their own — the server answers per viewer, so there is
 *   nothing to filter here.
 *
 * A stored value never comes back. A secret field that already holds one shows
 * as set and renders empty, so typing into it replaces the value and leaving it
 * alone keeps it. That is why the form sends only the keys that were touched.
 *
 * One renderer draws every plug-in's form, from the field types the pinned
 * definition declares — a new plug-in needs no code here.
 */

import { KeyRound, Loader2, Plug, ShieldCheck, TriangleAlert } from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";

import type { CommunityPluginConnectionRead } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  useConnectPlugin,
  useDisconnectPlugin,
  useUpdatePluginConfig,
} from "@/hooks/useCommunityPluginDetail";
import { getErrorMessage } from "@/lib/errorMessage";
import { toast } from "@/lib/mascotToast";
import { localized } from "@/lib/widgets/widgetMeta";

/** One typed input in a connection's form, as the pinned definition declares
 *  it. The read carries fields and the access hint untyped, because their shape
 *  is the manifest's rather than the API's. */
interface PluginConnectionField {
  key: string;
  type: "string" | "secret" | "url" | "bool" | "select" | "int";
  label: Record<string, string>;
  required?: boolean;
  options?: string[];
  /** Returned by the plug-in when a vendor flow finishes — never typed. */
  managed?: boolean;
}

/** A value being set, or `null` to clear it. */
type PluginConfigValue = string | number | boolean | null;

export interface PluginConnectionsPanelProps {
  pluginId: number;
  connections: CommunityPluginConnectionRead[];
  /** Holds the seat, which sets the community-wide connections. */
  canManage: boolean;
  /** Plug-ins are managed by whoever runs the server: the community-wide
   * connections are read-only. A member's own account still connects. */
  closed?: boolean;
}

export function PluginConnectionsPanel({
  pluginId,
  connections,
  canManage,
  closed = false,
}: PluginConnectionsPanelProps) {
  const { t } = useTranslation(["plugins"]);

  if (!connections.length) {
    return <p className="text-muted-foreground text-sm">{t("plugins:connections.none")}</p>;
  }

  return (
    <div className="space-y-4">
      {connections.map((connection) =>
        connection.scope === "static" ? (
          <CommunityConnection
            key={connection.id}
            pluginId={pluginId}
            connection={connection}
            canManage={canManage && !closed}
          />
        ) : (
          <PersonalConnection key={connection.id} pluginId={pluginId} connection={connection} />
        )
      )}
    </div>
  );
}

/** The shared frame: name, what it wants access to, and whether it is set. */
function ConnectionShell({
  connection,
  icon,
  scopeLabel,
  children,
}: {
  connection: CommunityPluginConnectionRead;
  icon: React.ReactNode;
  scopeLabel: string;
  children: React.ReactNode;
}) {
  const { t, i18n } = useTranslation(["plugins"]);
  const name = localized(connection.label, i18n.language) ?? connection.id;
  const hint = connection.access_hint as { api?: string; scopes?: string[] } | null;

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <header className="flex flex-wrap items-center gap-2">
        {icon}
        <h3 className="font-medium text-sm">{name}</h3>
        <Badge variant="outline">{scopeLabel}</Badge>
        {connection.satisfied ? (
          <Badge variant="secondary">{t("plugins:connections.set")}</Badge>
        ) : (
          <Badge variant="outline">{t("plugins:connections.notSet")}</Badge>
        )}
      </header>

      {/* Truth in advertising: the API and permissions this asks for, so an
          admin can mint the smallest credential that works. */}
      {hint?.api || hint?.scopes?.length ? (
        <p className="text-muted-foreground text-xs">
          {t("plugins:connections.accessHint", {
            api: hint.api ?? "—",
            scopes: hint.scopes?.length
              ? hint.scopes.join(", ")
              : t("plugins:connections.noScopes"),
          })}
        </p>
      ) : null}

      {children}
    </section>
  );
}

// --- the community's own credential ---------------------------------------------

function CommunityConnection({
  pluginId,
  connection,
  canManage,
}: {
  pluginId: number;
  connection: CommunityPluginConnectionRead;
  canManage: boolean;
}) {
  const { t, i18n } = useTranslation(["plugins", "common"]);
  const [draft, setDraft] = useState<Record<string, PluginConfigValue>>({});
  const save = useUpdatePluginConfig(pluginId);
  const clear = useDisconnectPlugin(pluginId);
  const connect = useConnectPlugin(pluginId);

  // Only what was touched. A secret already stored renders empty, so sending
  // untouched keys would clear the values the admin came here to keep.
  const touched = Object.keys(draft);

  // A managed field is filled when a vendor flow finishes, never typed here,
  // so a connection whose every field is managed has no form at all — which is
  // exactly the case a flow exists for.
  const fields = connection.fields as unknown as PluginConnectionField[];
  const typed = fields.filter((field) => !field.managed);
  const vendorFlow = connection.runs_flow;

  // What the flow recorded, shown rather than reduced to "Set". Otherwise the
  // admin who just chose an account at a vendor has no way to see which one
  // they chose — and no way to notice they chose the wrong one. Secrets are
  // absent by construction: `values` carries the non-secret half and the other
  // one is never sent back.
  const recorded = fields.filter(
    (field) => field.managed && connection.values[field.key] !== undefined
  );

  const start = () =>
    connect.mutate(connection.id, {
      onSuccess: (started) => {
        // A new tab rather than a redirect, so the admin comes back to where
        // they were; `noopener` keeps the vendor's page from reaching into
        // this one. The address is the server's to build — see
        // PersonalConnection.
        if (started.connect_url) {
          window.open(started.connect_url, "_blank", "noopener,noreferrer");
          toast.success(t("plugins:connections.connectOpened"));
          return;
        }
        toast.error(t("plugins:connections.connectUnavailable"));
      },
      onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
    });

  const submit = () => {
    save.mutate(
      { [connection.id]: draft },
      {
        onSuccess: () => {
          setDraft({});
          toast.success(t("plugins:connections.saved"));
        },
        onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
      }
    );
  };

  return (
    <ConnectionShell
      connection={connection}
      icon={<KeyRound className="h-4 w-4 text-muted-foreground" aria-hidden />}
      scopeLabel={t("plugins:connections.communityScope")}
    >
      {canManage ? (
        <>
          {vendorFlow && (
            <p className="text-muted-foreground text-sm">
              {t("plugins:connections.communityFlowExplainer")}
            </p>
          )}
          {recorded.length > 0 && (
            <dl className="grid gap-x-3 gap-y-1 text-sm sm:grid-cols-[max-content_1fr]">
              {recorded.map((field) => (
                <Fragment key={field.key}>
                  <dt className="text-muted-foreground">
                    {localized(field.label, i18n.language) ?? field.key}
                  </dt>
                  <dd className="break-all">{String(connection.values[field.key])}</dd>
                </Fragment>
              ))}
            </dl>
          )}
          {typed.length > 0 && (
            <div className="grid grid-cols-pair gap-3">
              {typed.map((field) => (
                <ConnectionFieldInput
                  key={field.key}
                  field={field}
                  connection={connection}
                  value={draft[field.key]}
                  onChange={(value) => setDraft((prev) => ({ ...prev, [field.key]: value }))}
                />
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            {vendorFlow && (
              <Button size="sm" onClick={start} disabled={connect.isPending}>
                {connect.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {connection.satisfied
                  ? t("plugins:connections.reconnect")
                  : t("plugins:connections.connect")}
              </Button>
            )}
            {typed.length > 0 && (
              <Button size="sm" onClick={submit} disabled={!touched.length || save.isPending}>
                {save.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {t("common:save")}
              </Button>
            )}
            {connection.satisfied && (
              <Button
                size="sm"
                variant="outline"
                disabled={clear.isPending}
                onClick={() =>
                  clear.mutate(connection.id, {
                    onSuccess: () => toast.success(t("plugins:connections.cleared")),
                    onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
                  })
                }
              >
                {t("plugins:connections.clear")}
              </Button>
            )}
          </div>
        </>
      ) : (
        // Not a secret, and useful: a member seeing a widget sit dark should be
        // able to tell whether an admin still has something to fill in.
        <p className="text-muted-foreground text-sm">
          {connection.satisfied
            ? t("plugins:connections.memberSet")
            : t("plugins:connections.memberNotSet")}
        </p>
      )}
    </ConnectionShell>
  );
}

/** One input, drawn from the field type the pinned definition declares. */
function ConnectionFieldInput({
  field,
  connection,
  value,
  onChange,
}: {
  field: PluginConnectionField;
  connection: CommunityPluginConnectionRead;
  value: PluginConfigValue;
  onChange: (value: PluginConfigValue) => void;
}) {
  const { t, i18n } = useTranslation(["plugins"]);
  const label = localized(field.label, i18n.language) ?? field.key;
  const isSet = connection.has_value[field.key] === true;
  const stored = connection.values[field.key];
  const id = `${connection.id}-${field.key}`;

  if (field.type === "bool") {
    const current = typeof value === "boolean" ? value : stored === true;
    return (
      <div className="flex items-center gap-2">
        <Switch id={id} checked={current} onCheckedChange={onChange} />
        <Label htmlFor={id}>{label}</Label>
      </div>
    );
  }

  if (field.type === "select") {
    const current = typeof value === "string" ? value : (stored as string | undefined);
    return (
      <div className="space-y-1.5">
        <Label htmlFor={id}>{label}</Label>
        <Select value={current ?? ""} onValueChange={onChange}>
          <SelectTrigger id={id}>
            <SelectValue placeholder={t("plugins:connections.choose")} />
          </SelectTrigger>
          <SelectContent>
            {(field.options ?? []).map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    );
  }

  const isSecret = field.type === "secret";
  const current =
    typeof value === "string" || typeof value === "number"
      ? String(value)
      : isSecret
        ? ""
        : ((stored as string | number | undefined) ?? "");

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>
        {label}
        {field.required && <span aria-hidden> *</span>}
      </Label>
      <Input
        id={id}
        // A stored secret is never sent back, so the field starts empty and
        // says it is already set instead. Typing replaces it; leaving it alone
        // keeps it.
        type={isSecret ? "password" : field.type === "int" ? "number" : "text"}
        autoComplete={isSecret ? "new-password" : "off"}
        placeholder={
          isSecret && isSet ? t("plugins:connections.secretSet") : t("plugins:connections.empty")
        }
        value={String(current)}
        onChange={(event) =>
          onChange(
            field.type === "int"
              ? event.target.value === ""
                ? null
                : Number(event.target.value)
              : event.target.value
          )
        }
      />
    </div>
  );
}

// --- a member's own account --------------------------------------------------

function PersonalConnection({
  pluginId,
  connection,
}: {
  pluginId: number;
  connection: CommunityPluginConnectionRead;
}) {
  const { t } = useTranslation(["plugins", "common"]);
  const connect = useConnectPlugin(pluginId);
  const disconnect = useDisconnectPlugin(pluginId);

  const start = () =>
    connect.mutate(connection.id, {
      onSuccess: (started) => {
        // The server builds the vendor's address; the client never does. A
        // new tab rather than a redirect, so the member comes back to where
        // they were, and `noopener` keeps the vendor's page from reaching into
        // this one.
        if (started.connect_url) {
          window.open(started.connect_url, "_blank", "noopener,noreferrer");
          toast.success(t("plugins:connections.connectOpened"));
          return;
        }
        toast.error(t("plugins:connections.connectUnavailable"));
      },
      onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
    });

  return (
    <ConnectionShell
      connection={connection}
      icon={<Plug className="h-4 w-4 text-muted-foreground" aria-hidden />}
      scopeLabel={t("plugins:connections.personalScope")}
    >
      <p className="text-muted-foreground text-sm">{t("plugins:connections.personalExplainer")}</p>

      {connection.blocked ? (
        <p className="flex items-center gap-2 text-destructive text-sm">
          <TriangleAlert className="h-4 w-4" aria-hidden />
          {t("plugins:connections.blocked")}
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {connection.status === "expired" ? (
            // The vendor would not renew it: nothing reaches it until the
            // member connects again.
            <span className="flex items-center gap-1.5 text-amber-600 text-sm dark:text-amber-400">
              <TriangleAlert className="h-4 w-4" aria-hidden />
              {t("plugins:connections.expired")}
            </span>
          ) : connection.status ? (
            <span className="flex items-center gap-1.5 text-sm">
              <ShieldCheck className="h-4 w-4 text-muted-foreground" aria-hidden />
              {connection.account_label
                ? t("plugins:connections.connectedAs", { account: connection.account_label })
                : t(`plugins:connections.status.${connection.status}`, {
                    defaultValue: connection.status,
                  })}
            </span>
          ) : null}

          <Button size="sm" onClick={start} disabled={connect.isPending}>
            {connect.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {connection.status
              ? t("plugins:connections.reconnect")
              : t("plugins:connections.connect")}
          </Button>

          {connection.status && (
            <Button
              size="sm"
              variant="outline"
              disabled={disconnect.isPending}
              onClick={() =>
                disconnect.mutate(connection.id, {
                  onSuccess: () => toast.success(t("plugins:connections.disconnected")),
                  onError: (error) => toast.error(getErrorMessage(error, "plugins:error")),
                })
              }
            >
              {t("plugins:connections.disconnect")}
            </Button>
          )}
        </div>
      )}
    </ConnectionShell>
  );
}

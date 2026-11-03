/**
 * Community → Initiatives: what every initiative in the community uses.
 *
 * A tool's switch, or a permission of the built-in member role, set here
 * stands over each initiative's own, and its managers see it as set. Left to
 * "each initiative", it is theirs as before. The community may also keep its
 * initiatives to their built-in roles.
 */

import { useTranslation } from "react-i18next";

import type {
  InitiativeDefaultsUpdate,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  EXTRA_PERMISSION_KEYS,
  PERMISSION_LABEL_KEYS,
  useInitiativeDefaults,
  useSetInitiativeDefaults,
} from "@/hooks/useInitiativeRoles";
import {
  SIDEBAR_TOOLS,
  toolCamelPlural,
  toolCreatePermission,
  toolViewPermission,
} from "@/lib/tools";

type Choice = "initiative" | "on" | "off";

const choiceOf = (value: boolean | undefined): Choice =>
  value === undefined ? "initiative" : value ? "on" : "off";

const stored = (choice: Choice): boolean | null =>
  choice === "initiative" ? null : choice === "on";

export const CommunityInitiativeDefaultsCard = () => {
  const { t } = useTranslation("initiatives");
  const defaults = useInitiativeDefaults().data;
  const update = useSetInitiativeDefaults();

  if (!defaults) return null;

  const save = (data: InitiativeDefaultsUpdate) => update.mutate(data);

  const choice = (
    id: string,
    label: string,
    value: boolean | undefined,
    onPick: (v: boolean | null) => void
  ) => (
    <Select
      value={choiceOf(value)}
      disabled={update.isPending}
      onValueChange={(picked) => onPick(stored(picked as Choice))}
    >
      <SelectTrigger id={id} aria-label={label} className="w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="initiative">{t("communityDefaults.choice.initiative")}</SelectItem>
        <SelectItem value="on">{t("communityDefaults.choice.on")}</SelectItem>
        <SelectItem value="off">{t("communityDefaults.choice.off")}</SelectItem>
      </SelectContent>
    </Select>
  );

  const member = (key: PermissionKey) => defaults.member_permissions[key];
  const setMember = (key: PermissionKey) => (value: boolean | null) =>
    save({ member_permissions: { [key]: value } });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("communityDefaults.title")}</CardTitle>
        <CardDescription>{t("communityDefaults.description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <h3 className="font-medium text-sm">{t("communityDefaults.toolsHeading")}</h3>
          {SIDEBAR_TOOLS.map((tool: Tool) => {
            const label = t(`${toolCamelPlural(tool)}Feature` as never);
            return (
              <div key={tool} className="flex flex-wrap items-center justify-between gap-2">
                <Label htmlFor={`community-tool-${tool}`}>{label}</Label>
                {choice(`community-tool-${tool}`, label, defaults.tools[tool], (value) =>
                  save({ tools: { [tool]: value } })
                )}
              </div>
            );
          })}
        </section>

        <section className="space-y-3">
          <div>
            <h3 className="font-medium text-sm">{t("communityDefaults.memberHeading")}</h3>
            <p className="text-muted-foreground text-xs">{t("communityDefaults.memberHelp")}</p>
          </div>
          {SIDEBAR_TOOLS.flatMap((tool: Tool) =>
            [toolViewPermission(tool), toolCreatePermission(tool)].map((raw) => {
              const key = raw as PermissionKey;
              const label = t(PERMISSION_LABEL_KEYS[key] as never);
              return (
                <div key={key} className="flex flex-wrap items-center justify-between gap-2">
                  <Label htmlFor={`community-member-${key}`}>{label}</Label>
                  {choice(`community-member-${key}`, label, member(key), setMember(key))}
                </div>
              );
            })
          )}
          {EXTRA_PERMISSION_KEYS.map((key) => {
            const label = t(PERMISSION_LABEL_KEYS[key] as never);
            return (
              <div key={key} className="flex flex-wrap items-center justify-between gap-2">
                <Label htmlFor={`community-member-${key}`}>{label}</Label>
                {choice(`community-member-${key}`, label, member(key), setMember(key))}
              </div>
            );
          })}
        </section>

        <div className="flex items-start justify-between gap-4 border-t pt-4">
          <div className="space-y-1">
            <Label htmlFor="community-custom-roles" className="font-medium">
              {t("communityDefaults.customRolesLabel")}
            </Label>
            <p className="text-muted-foreground text-sm">
              {t("communityDefaults.customRolesHelp")}
            </p>
          </div>
          <Switch
            id="community-custom-roles"
            checked={defaults.custom_roles}
            disabled={update.isPending}
            onCheckedChange={(on) => save({ custom_roles: on })}
          />
        </div>
      </CardContent>
    </Card>
  );
};

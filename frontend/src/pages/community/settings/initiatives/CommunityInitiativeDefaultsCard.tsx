/**
 * Community → Initiatives: the rules every initiative follows.
 *
 * Each initiative decides its own tools, what its built-in Member role may do
 * and what members hold of each plug-in placed in it. A rule set here stands
 * over that in every initiative, and their managers see it as set. Most of
 * those answers are left to the initiatives, so the card lists only the rules
 * there are, one sentence per tool or plug-in; the dialog adds or changes one
 * and says, before it is saved, which initiatives it changes.
 */

import { Blocks, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CommunityPluginRead,
  InitiativeDefaultsRead,
  InitiativeRead,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import { useCommunityPlugins } from "@/hooks/useCommunityPlugins";
import {
  EXTRA_PERMISSION_KEYS,
  useInitiativeDefaults,
  useSetInitiativeDefaults,
} from "@/hooks/useInitiativeRoles";
import { permissionName } from "@/lib/pluginSurfaces";
import {
  SIDEBAR_TOOLS,
  TOOL_ICONS,
  toolCamelPlural,
  toolCreatePermission,
  toolPlural,
  toolViewPermission,
} from "@/lib/tools";
import { Button } from "@/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog";
import { Empty, EmptyDescription } from "@/ui/empty";
import { Field } from "@/ui/field";
import { Label } from "@/ui/label";
import { listFormat } from "@/ui/lib/intl";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/ui/select";
import { Switch } from "@/ui/switch";

type Answer = "each" | "on" | "off";
const ANSWERS: readonly Answer[] = ["each", "on", "off"];
/** One rule: a tool's switch and each Member permission that is the tool's,
 *  or what members hold of each of a plug-in's initiative permissions, by id. */
type Rule = { tool: Answer; perms: Partial<Record<string, Answer>> };
type RuleKey = "tool" | PermissionKey;
/** What a rule is about: a tool, or an installed plug-in. */
type Subject = Tool | CommunityPluginRead;

const answerOf = (value: boolean | undefined): Answer =>
  value === undefined ? "each" : value ? "on" : "off";
const stored = (answer: Answer | undefined): boolean | null =>
  answer === undefined || answer === "each" ? null : answer === "on";

/** The tool's Member permissions: viewing it, creating in it, and any extra
 *  one named for it (`dashboards_run_as_initiative`). */
const keysOf = (tool: Tool): PermissionKey[] => [
  toolViewPermission(tool),
  toolCreatePermission(tool),
  ...EXTRA_PERMISSION_KEYS.filter((key) => key.startsWith(`${toolPlural(tool)}_`)),
];

/** Which strings a key's question and changes read from. */
const kindOf = (tool: Tool, key: RuleKey): string =>
  key === "tool"
    ? "tool"
    : key === toolViewPermission(tool)
      ? "view"
      : key === toolCreatePermission(tool)
        ? "create"
        : `extra.${key}`;

/** The plug-in's permissions an initiative's roles hold. */
const heldInInitiatives = (install: CommunityPluginRead) =>
  install.permissions.filter((permission) => permission.level === "initiative");

const ruleOf = (defaults: InitiativeDefaultsRead, subject: Subject): Rule =>
  typeof subject === "string"
    ? {
        tool: answerOf(defaults.tools[subject]),
        perms: Object.fromEntries(
          keysOf(subject).map((key) => [key, answerOf(defaults.member_permissions[key])])
        ),
      }
    : {
        tool: "each",
        perms: Object.fromEntries(
          defaults.plugin_member_permissions
            .filter((rule) => rule.install_id === subject.id)
            .map((rule) => [rule.permission, answerOf(rule.enabled)])
        ),
      };

/** A subject as the tool picker's value. */
const subjectValue = (subject: Subject): string =>
  typeof subject === "string" ? subject : String(subject.id);

const hasRule = (rule: Rule) =>
  rule.tool !== "each" || Object.values(rule.perms).some((answer) => answer !== "each");

const answerFor = (rule: Rule, key: RuleKey): Answer =>
  key === "tool" ? rule.tool : (rule.perms[key] ?? "each");

export const CommunityInitiativeDefaultsCard = ({
  initiatives,
}: {
  /** The community's live initiatives, which a rule's changes are named from. */
  initiatives: InitiativeRead[];
}) => {
  const { t, i18n } = useTranslation(["initiatives", "common", "plugins"]);
  const defaults = useInitiativeDefaults().data;
  const update = useSetInitiativeDefaults();
  const plugins = useCommunityPlugins().data?.items ?? [];
  const [open, setOpen] = useState<{ subject: Subject; adding: boolean; draft: Rule } | null>(null);

  if (!defaults) return null;

  const toolName = (tool: Tool) => t(`${toolCamelPlural(tool)}Feature` as never);
  const nameOf = (subject: Subject) =>
    typeof subject === "string" ? toolName(subject) : subject.name;
  const items = (tool: Tool) => t(`communityDefaults.items.${toolCamelPlural(tool)}` as never);
  const subjects: Subject[] = [...SIDEBAR_TOOLS, ...plugins];
  const ruled = subjects.filter((subject) => hasRule(ruleOf(defaults, subject)));
  const free = subjects.filter((subject) => !ruled.includes(subject));

  /** The rule as sentences: a tool's switch first, then what members may do. */
  const sentences = (subject: Subject, rule: Rule): string => {
    if (typeof subject !== "string") {
      return heldInInitiatives(subject)
        .flatMap((permission) => {
          const answer = rule.perms[permission.id] ?? "each";
          return answer === "each"
            ? []
            : [
                t(`communityDefaults.rule.plugin.${answer}` as never, {
                  permission: permissionName(permission, i18n.language, t),
                }),
              ];
        })
        .join(" ");
    }
    const tool = subject;
    if (rule.tool === "off") return t("communityDefaults.rule.toolOff");
    const out = rule.tool === "on" ? [t("communityDefaults.rule.toolOn")] : [];
    const view = answerFor(rule, toolViewPermission(tool));
    const create = answerFor(rule, toolCreatePermission(tool));
    const member =
      view === "on"
        ? { on: "viewCreate", off: "viewNotCreate", each: "view" }[create]
        : view === "off"
          ? "notView"
          : { on: "create", off: "notCreate", each: null }[create];
    if (member) {
      out.push(t(`communityDefaults.rule.${member}` as never, { items: items(tool) }));
    }
    for (const key of keysOf(tool).slice(2)) {
      const answer = answerFor(rule, key);
      if (answer !== "each") out.push(t(`communityDefaults.extra.${key}.${answer}` as never));
    }
    return out.join(" ");
  };

  /** What saving `draft` over `current` changes in each live initiative:
   *  where a value turns on, and where it turns off. A member permission is
   *  what members can reach, so it counts only where they reach its tool or
   *  plug-in afterwards: a tool where its switch is on, so turning a tool off
   *  is said once, and a plug-in where it is placed. */
  const changes = (subject: Subject, current: Rule, draft: Rule): string[] => {
    const tool = typeof subject === "string" ? subject : null;
    const install = typeof subject === "string" ? null : subject;
    const named = new Map(
      (install ? heldInInitiatives(install) : []).map((permission) => [
        permission.id,
        permissionName(permission, i18n.language, t),
      ])
    );
    /** Whether `key` is a tool's switch rather than a permission. */
    const isSwitch = (key: string) => tool !== null && key === "tool";
    const value = (rule: Rule, key: string, id: number) => {
      const answer = tool ? answerFor(rule, key as RuleKey) : (rule.perms[key] ?? "each");
      if (answer !== "each") return answer === "on";
      const own = !tool
        ? defaults.own_plugin_member_permissions.find(
            (one) => one.install_id === install?.id && one.permission === key
          )?.initiative_ids
        : isSwitch(key)
          ? defaults.own_tools[tool]
          : defaults.own_member_permissions[key as PermissionKey];
      return own?.includes(id) ?? false;
    };
    const reaches = (rule: Rule, id: number) =>
      tool ? value(rule, "tool", id) : Boolean(install?.placed_initiative_ids.includes(id));
    const holds = (rule: Rule, key: string, id: number) =>
      reaches(rule, id) && (isSwitch(key) || value(rule, key, id));
    const names = (ids: number[]) =>
      listFormat(i18n.language).format(
        initiatives.filter((initiative) => ids.includes(initiative.id)).map((i) => i.name)
      );
    const keys = tool ? ["tool", ...keysOf(tool)] : [...named.keys()];
    const lines: string[] = [];
    for (const key of keys) {
      const reached = initiatives
        .map((initiative) => initiative.id)
        .filter((id) => isSwitch(key) || reaches(draft, id))
        .filter((id) => holds(current, key, id) !== holds(draft, key, id));
      for (const direction of ["on", "off"] as const) {
        const ids = reached.filter((id) => holds(draft, key, id) === (direction === "on"));
        if (ids.length > 0) {
          lines.push(
            tool
              ? t(
                  `communityDefaults.changes.${kindOf(tool, key as RuleKey)}.${direction}` as never,
                  {
                    tool: toolName(tool),
                    items: items(tool),
                    names: names(ids),
                  }
                )
              : t(`communityDefaults.changes.plugin.${direction}` as never, {
                  permission: named.get(key),
                  names: names(ids),
                })
          );
        }
      }
    }
    return lines;
  };

  const save = (subject: Subject, rule: Rule) =>
    update.mutate(
      typeof subject === "string"
        ? {
            tools: { [subject]: stored(rule.tool) },
            member_permissions: Object.fromEntries(
              keysOf(subject).map((key) => [key, stored(rule.perms[key])])
            ),
          }
        : {
            plugin_member_permissions: heldInInitiatives(subject).map((permission) => ({
              install_id: subject.id,
              permission: permission.id,
              enabled: stored(rule.perms[permission.id]),
            })),
          },
      { onSuccess: () => setOpen(null) }
    );

  /** One answer changed, with a tool's pair rule kept: members can't create
   *  what they can't view, and a tool off everywhere leaves them nothing to
   *  answer. A plug-in's answers stand alone. */
  const answer = (key: string, value: Answer) => {
    if (!open) return;
    const draft: Rule = { tool: open.draft.tool, perms: { ...open.draft.perms } };
    const tool = open.subject;
    if (typeof tool !== "string") {
      draft.perms[key] = value;
      setOpen({ ...open, draft });
      return;
    }
    const viewKey = toolViewPermission(tool);
    const createKey = toolCreatePermission(tool);
    if (key === "tool") {
      draft.tool = value;
      if (value === "off") {
        for (const perm of keysOf(tool)) draft.perms[perm] = "each";
      }
    } else {
      draft.perms[key] = value;
    }
    if (key === createKey && value === "on") draft.perms[viewKey] = "on";
    if (key === viewKey && value === "off") draft.perms[createKey] = "off";
    if (key === viewKey && value === "each" && draft.perms[createKey] === "on") {
      draft.perms[createKey] = "each";
    }
    setOpen({ ...open, draft });
  };

  const question = (subject: Subject, draft: Rule, key: string) => {
    const id = `community-rule-${key}`;
    const tool = typeof subject === "string" ? subject : null;
    // Members can't create what they can't view.
    const pinned =
      tool !== null &&
      key === toolCreatePermission(tool) &&
      answerFor(draft, toolViewPermission(tool)) === "off";
    const permission =
      typeof subject === "string" ? null : heldInInitiatives(subject).find((one) => one.id === key);
    return (
      <div key={key} className="space-y-2">
        <p id={id} className="font-medium text-sm">
          {tool
            ? t(`communityDefaults.question.${kindOf(tool, key as RuleKey)}` as never, {
                tool: toolName(tool),
                items: items(tool),
              })
            : t("communityDefaults.question.plugin", {
                permission: permission ? permissionName(permission, i18n.language, t) : key,
              })}
        </p>
        <RadioGroup
          aria-labelledby={id}
          value={tool ? answerFor(draft, key as RuleKey) : (draft.perms[key] ?? "each")}
          onValueChange={(next) => answer(key, next as Answer)}
          className="flex flex-wrap gap-x-5 gap-y-2"
        >
          {ANSWERS.map((option) => (
            <div key={option} className="flex items-center gap-2">
              <RadioGroupItem
                id={`${id}-${option}`}
                value={option}
                disabled={pinned && option !== "off"}
              />
              <Label htmlFor={`${id}-${option}`} className="font-normal">
                {t(
                  `communityDefaults.answer.${tool && key === "tool" ? "tool" : "member"}.${option}` as never
                )}
              </Label>
            </div>
          ))}
        </RadioGroup>
        {pinned && (
          <p className="text-muted-foreground text-xs">{t("communityDefaults.createNeedsView")}</p>
        )}
      </div>
    );
  };

  const dialog = (() => {
    if (!open) return null;
    const { subject, adding, draft } = open;
    const ruleSet = hasRule(draft);
    const removing = !adding && !ruleSet;
    const name = nameOf(subject);
    const lines = changes(subject, ruleOf(defaults, subject), draft);
    return (
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {adding
              ? t("communityDefaults.addTitle")
              : t("communityDefaults.editTitle", { tool: name })}
          </DialogTitle>
          <DialogDescription>{t("communityDefaults.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {adding && (
            <Field label={t("communityDefaults.toolLabel")}>
              <Select
                value={subjectValue(subject)}
                onValueChange={(value) => {
                  const next = free.find((option) => subjectValue(option) === value);
                  if (next) setOpen({ subject: next, adding: true, draft: ruleOf(defaults, next) });
                }}
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {free.map((option) => (
                    <SelectItem key={subjectValue(option)} value={subjectValue(option)}>
                      {nameOf(option)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          {typeof subject !== "string" ? (
            heldInInitiatives(subject).map((permission) => question(subject, draft, permission.id))
          ) : (
            <>
              {question(subject, draft, "tool")}
              {draft.tool === "off" ? (
                <p className="text-muted-foreground text-xs">
                  {t("communityDefaults.offNote", { tool: name })}
                </p>
              ) : (
                keysOf(subject).map((key) => question(subject, draft, key))
              )}
            </>
          )}
          <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
            <p>
              <span className="font-medium">{t("communityDefaults.reads")}</span>{" "}
              {ruleSet ? sentences(subject, draft) : t("communityDefaults.noRule")}
            </p>
            <div>
              <p className="font-medium">{t("communityDefaults.changesHeading")}</p>
              {lines.length > 0 ? (
                <ul className="list-disc space-y-0.5 pl-5">
                  {lines.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground">{t("communityDefaults.changesNone")}</p>
              )}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(null)}>
            {t("common:cancel")}
          </Button>
          <Button
            variant={removing ? "destructive" : "default"}
            disabled={update.isPending || (adding && !ruleSet)}
            onClick={() => save(subject, draft)}
          >
            {removing ? t("communityDefaults.remove") : t("communityDefaults.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    );
  })();

  return (
    <>
      <SettingsSection
        title={t("communityDefaults.title")}
        description={t("communityDefaults.description")}
        action={
          free.length > 0 && (
            <Button
              variant="outline"
              onClick={() =>
                setOpen({ subject: free[0], adding: true, draft: ruleOf(defaults, free[0]) })
              }
            >
              <Plus className="h-4 w-4" />
              {t("communityDefaults.add")}
            </Button>
          )
        }
        contentClassName="space-y-6"
      >
        {ruled.length > 0 ? (
          <ul className="divide-y rounded-md border">
            {ruled.map((subject) => {
              const Icon = typeof subject === "string" ? TOOL_ICONS[subject] : Blocks;
              const name = nameOf(subject);
              return (
                <li key={subjectValue(subject)} className="flex items-center gap-3 px-4 py-3">
                  <Icon className="h-4 w-4 shrink-0 self-start text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm">{name}</p>
                    <p className="text-sm">{sentences(subject, ruleOf(defaults, subject))}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t("communityDefaults.editLabel", { tool: name })}
                    onClick={() =>
                      setOpen({ subject, adding: false, draft: ruleOf(defaults, subject) })
                    }
                  >
                    {t("common:edit")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("communityDefaults.removeLabel", { tool: name })}
                    disabled={update.isPending}
                    onClick={() => save(subject, { tool: "each", perms: {} })}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </li>
              );
            })}
          </ul>
        ) : (
          <Empty className="border p-6">
            <EmptyDescription>{t("communityDefaults.empty")}</EmptyDescription>
          </Empty>
        )}

        <div className="border-t pt-4">
          <SettingsRow
            label={t("communityDefaults.customRolesLabel")}
            description={t("communityDefaults.customRolesHelp")}
          >
            <Switch
              checked={defaults.custom_roles}
              disabled={update.isPending}
              onCheckedChange={(on) => update.mutate({ custom_roles: on })}
            />
          </SettingsRow>
        </div>
      </SettingsSection>

      <Dialog open={open !== null} onOpenChange={(next) => !next && setOpen(null)}>
        {dialog}
      </Dialog>
    </>
  );
};

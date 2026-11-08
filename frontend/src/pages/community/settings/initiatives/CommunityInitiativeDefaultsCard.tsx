/**
 * Community → Initiatives: the rules every initiative follows.
 *
 * Each initiative decides its own tools and what its built-in Member role may
 * do. A rule set here stands over that in every initiative, and their managers
 * see it as set. Most of those answers are left to the initiatives, so the card
 * lists only the rules there are, one sentence per tool; the dialog adds or
 * changes one and says, before it is saved, which initiatives it changes.
 */

import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  InitiativeDefaultsRead,
  InitiativeRead,
  PermissionKey,
  Tool,
} from "@/api/generated/initiativeAPI.schemas";
import { SettingsRow, SettingsSection } from "@/components/settings/SettingsSection";
import {
  EXTRA_PERMISSION_KEYS,
  useInitiativeDefaults,
  useSetInitiativeDefaults,
} from "@/hooks/useInitiativeRoles";
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
/** One tool's rule: its switch, and each Member permission that is the tool's. */
type Rule = { tool: Answer; perms: Partial<Record<PermissionKey, Answer>> };
type RuleKey = "tool" | PermissionKey;

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

const ruleOf = (defaults: InitiativeDefaultsRead, tool: Tool): Rule => ({
  tool: answerOf(defaults.tools[tool]),
  perms: Object.fromEntries(
    keysOf(tool).map((key) => [key, answerOf(defaults.member_permissions[key])])
  ),
});

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
  const { t, i18n } = useTranslation(["initiatives", "common"]);
  const defaults = useInitiativeDefaults().data;
  const update = useSetInitiativeDefaults();
  const [open, setOpen] = useState<{ tool: Tool; adding: boolean; draft: Rule } | null>(null);

  if (!defaults) return null;

  const toolName = (tool: Tool) => t(`${toolCamelPlural(tool)}Feature` as never);
  const items = (tool: Tool) => t(`communityDefaults.items.${toolCamelPlural(tool)}` as never);
  const ruled = SIDEBAR_TOOLS.filter((tool) => hasRule(ruleOf(defaults, tool)));
  const free = SIDEBAR_TOOLS.filter((tool) => !ruled.includes(tool));

  /** The rule as sentences: the switch first, then what members may do. */
  const sentences = (tool: Tool, rule: Rule): string => {
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
   *  what members can reach, so it counts with the tool's switch, and only
   *  where the tool is on afterwards: turning a tool off is said once. */
  const changes = (tool: Tool, current: Rule, draft: Rule): string[] => {
    const value = (rule: Rule, key: RuleKey, id: number) => {
      const answer = answerFor(rule, key);
      if (answer !== "each") return answer === "on";
      const own = key === "tool" ? defaults.own_tools[tool] : defaults.own_member_permissions[key];
      return own?.includes(id) ?? false;
    };
    const holds = (rule: Rule, key: RuleKey, id: number) =>
      value(rule, "tool", id) && (key === "tool" || value(rule, key, id));
    const names = (ids: number[]) =>
      listFormat(i18n.language).format(
        initiatives.filter((initiative) => ids.includes(initiative.id)).map((i) => i.name)
      );
    const lines: string[] = [];
    for (const key of ["tool" as const, ...keysOf(tool)]) {
      const reached = initiatives
        .map((initiative) => initiative.id)
        .filter((id) => key === "tool" || holds(draft, "tool", id))
        .filter((id) => holds(current, key, id) !== holds(draft, key, id));
      for (const direction of ["on", "off"] as const) {
        const ids = reached.filter((id) => holds(draft, key, id) === (direction === "on"));
        if (ids.length > 0) {
          lines.push(
            t(`communityDefaults.changes.${kindOf(tool, key)}.${direction}` as never, {
              tool: toolName(tool),
              items: items(tool),
              names: names(ids),
            })
          );
        }
      }
    }
    return lines;
  };

  const save = (tool: Tool, rule: Rule) =>
    update.mutate(
      {
        tools: { [tool]: stored(rule.tool) },
        member_permissions: Object.fromEntries(
          keysOf(tool).map((key) => [key, stored(rule.perms[key])])
        ),
      },
      { onSuccess: () => setOpen(null) }
    );

  /** One answer changed, with the pair rule kept: members can't create what
   *  they can't view, and a tool off everywhere leaves them nothing to answer. */
  const answer = (key: RuleKey, value: Answer) => {
    if (!open) return;
    const viewKey = toolViewPermission(open.tool);
    const createKey = toolCreatePermission(open.tool);
    const draft: Rule = { tool: open.draft.tool, perms: { ...open.draft.perms } };
    if (key === "tool") {
      draft.tool = value;
      if (value === "off") {
        for (const perm of keysOf(open.tool)) draft.perms[perm] = "each";
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

  const question = (tool: Tool, draft: Rule, key: RuleKey) => {
    const id = `community-rule-${key}`;
    // Members can't create what they can't view.
    const pinned =
      key === toolCreatePermission(tool) && answerFor(draft, toolViewPermission(tool)) === "off";
    return (
      <div key={key} className="space-y-2">
        <p id={id} className="font-medium text-sm">
          {t(`communityDefaults.question.${kindOf(tool, key)}` as never, {
            tool: toolName(tool),
            items: items(tool),
          })}
        </p>
        <RadioGroup
          aria-labelledby={id}
          value={answerFor(draft, key)}
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
                  `communityDefaults.answer.${key === "tool" ? "tool" : "member"}.${option}` as never
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
    const { tool, adding, draft } = open;
    const ruleSet = hasRule(draft);
    const lines = changes(tool, ruleOf(defaults, tool), draft);
    const removing = !adding && !ruleSet;
    return (
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {adding
              ? t("communityDefaults.addTitle")
              : t("communityDefaults.editTitle", { tool: toolName(tool) })}
          </DialogTitle>
          <DialogDescription>{t("communityDefaults.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-5">
          {adding && (
            <Field label={t("communityDefaults.toolLabel")}>
              <Select
                value={tool}
                onValueChange={(next) =>
                  setOpen({
                    tool: next as Tool,
                    adding: true,
                    draft: ruleOf(defaults, next as Tool),
                  })
                }
              >
                <SelectTrigger className="w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {free.map((option) => (
                    <SelectItem key={option} value={option}>
                      {toolName(option)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          {question(tool, draft, "tool")}
          {draft.tool === "off" ? (
            <p className="text-muted-foreground text-xs">
              {t("communityDefaults.offNote", { tool: toolName(tool) })}
            </p>
          ) : (
            keysOf(tool).map((key) => question(tool, draft, key))
          )}
          <div className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
            <p>
              <span className="font-medium">{t("communityDefaults.reads")}</span>{" "}
              {ruleSet ? sentences(tool, draft) : t("communityDefaults.noRule")}
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
            onClick={() => save(tool, draft)}
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
                setOpen({ tool: free[0], adding: true, draft: ruleOf(defaults, free[0]) })
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
            {ruled.map((tool) => {
              const Icon = TOOL_ICONS[tool];
              const name = toolName(tool);
              return (
                <li key={tool} className="flex items-center gap-3 px-4 py-3">
                  <Icon className="h-4 w-4 shrink-0 self-start text-muted-foreground" aria-hidden />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-sm">{name}</p>
                    <p className="text-sm">{sentences(tool, ruleOf(defaults, tool))}</p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={t("communityDefaults.editLabel", { tool: name })}
                    onClick={() => setOpen({ tool, adding: false, draft: ruleOf(defaults, tool) })}
                  >
                    {t("common:edit")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={t("communityDefaults.removeLabel", { tool: name })}
                    disabled={update.isPending}
                    onClick={() => save(tool, { tool: "each", perms: {} })}
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

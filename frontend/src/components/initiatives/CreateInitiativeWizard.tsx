/**
 * Create an initiative, one question at a time.
 *
 * This is the first thing most people do in a community — a community now
 * arrives with no initiatives at all — so it is also the first real impression
 * the app makes. The old single form asked everything at once and hid the tools
 * behind an accordion labelled "Advanced", which meant the one decision that
 * actually shapes the place was the one nobody opened.
 *
 * Four questions, in the order somebody actually answers them:
 *
 *   1. What is it called
 *   2. What is it made of          — at least one tool, or there is no place to put anything
 *   3. Who can get in
 *   4. What can they do once in
 *
 * When it is the community's first initiative, step 1 opens by saying what an
 * initiative *is*. Nothing else in the app has had the chance to yet.
 *
 * Step 4 exists because of a gap nothing else closes. The built-in `member`
 * role ships view-only on projects and files and `create_*` off everywhere,
 * so an initiative created with a calendar has that calendar switched on for
 * its managers and invisible to everybody else. Asking here costs one screen;
 * finding out later costs somebody filing a bug about an empty sidebar.
 *
 * The caller owns the open state — a header button, the `?create=true` deep
 * link, and the redirect after a community is created all drive it — and owns
 * the permission gate. Creating is community-admin only, which the backend enforces
 * regardless.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { InitiativeCreate, InitiativeRead } from "@/api/generated/initiativeAPI.schemas";
import { InitiativeJoinPolicy, type Tool } from "@/api/generated/initiativeAPI.schemas";
import yonderTalking from "@/assets/yonder/talking.svg";
import { JoinPolicySection } from "@/components/initiatives/JoinPolicySection";
import { ToolsSection } from "@/components/initiatives/ToolsToggles";
import { Markdown } from "@/components/Markdown";
import { useGrantToolsToMembers } from "@/hooks/useInitiativeRoles";
import { useCreateInitiative } from "@/hooks/useInitiatives";
import { useWizard } from "@/hooks/useWizard";
import { docsUrl } from "@/lib/links";
import { toast } from "@/lib/mascotToast";
import { DEFAULT_ENABLED_TOOLS, TOOLS, toolViewPermission } from "@/lib/tools";
import { Button } from "@/ui/button";
import { ColorPickerPopover } from "@/ui/color-picker-popover";
import { DialogFooter } from "@/ui/dialog";
import { Field } from "@/ui/field";
import { Input } from "@/ui/input";
import { Label } from "@/ui/label";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";
import { Textarea } from "@/ui/textarea";
import { WizardBackButton, WizardDialog } from "@/ui/wizard-dialog";

const DEFAULT_INITIATIVE_COLOR = "#6366F1";

/** Where the idea is explained properly, for somebody who wants more than a
 *  paragraph. Opens in its own tab: the wizard is half-filled by this point. */
const INITIATIVES_DOC_URL = docsUrl("guides/initiatives/");

type Step = "details" | "tools" | "joining" | "members";

/** Four questions, each asked once and in this order — so the dots can count. */
const STEP_ORDER: Step[] = ["details", "tools", "joining", "members"];

/** What the ordinary roles may do with the tools this initiative starts with.
 *  "view" is the default because it is what the built-in member role already
 *  is — the wizard names the existing behaviour rather than quietly changing
 *  it, and "make things" is one click away for the groups that want it. */
type MemberAudience = "create" | "view" | "managers";

const MEMBER_AUDIENCES: MemberAudience[] = ["create", "view", "managers"];

/** The tools every new initiative starts with ticked. */
const defaultSelection = (): Record<string, boolean> =>
  Object.fromEntries(TOOLS.map((tool) => [tool, DEFAULT_ENABLED_TOOLS.has(tool)]));

export interface CreateInitiativeWizardProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The community has no initiatives yet, so this one has to introduce the
   *  idea as well as collect a name. */
  isFirst?: boolean;
  /** Called with the created initiative, for a caller that wants to go there. */
  onCreated?: (initiative: InitiativeRead) => void;
}

interface NextAction {
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  pending?: boolean;
  /** Submits the enclosing form (so Enter in a field advances) instead of
   *  calling `onClick`. */
  submit?: boolean;
}

export const CreateInitiativeWizard = ({
  open,
  onOpenChange,
  isFirst = false,
  onCreated,
}: CreateInitiativeWizardProps) => {
  const { t } = useTranslation("initiatives");

  const { step, go, back, canGoBack, reset } = useWizard<Step>("details");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(DEFAULT_INITIATIVE_COLOR);
  const [joinPolicy, setJoinPolicy] = useState<InitiativeJoinPolicy>(InitiativeJoinPolicy.private);
  const [selected, setSelected] = useState<Record<string, boolean>>(defaultSelection);
  const [audience, setAudience] = useState<MemberAudience>("view");

  const createInitiative = useCreateInitiative();
  // The grant takes its initiative id per call. The initiative does not exist
  // at this render, so a hook bound to one here would carry whatever state
  // held before the create resolved — which is nothing.
  const grantToMembers = useGrantToolsToMembers();

  const busy = createInitiative.isPending || grantToMembers.isPending;

  // A closed wizard is a finished one: the next person to open it starts over
  // rather than resuming somebody else's half-answered form.
  useEffect(() => {
    if (open) return;
    reset();
    setName("");
    setDescription("");
    setColor(DEFAULT_INITIATIVE_COLOR);
    setJoinPolicy(InitiativeJoinPolicy.private);
    setSelected(defaultSelection());
    setAudience("view");
  }, [open, reset]);

  const chosenTools = useMemo(() => TOOLS.filter((tool) => selected[tool]), [selected]);
  const trimmedName = name.trim();

  const stepTitle = useMemo(() => {
    switch (step) {
      case "details":
        return t("createWizard.detailsStep");
      case "tools":
        return t("createWizard.toolsStep");
      case "joining":
        return t("createWizard.joiningStep");
      case "members":
        return t("createWizard.membersStep");
    }
  }, [step, t]);

  const handleSubmit = useCallback(async () => {
    if (!trimmedName) {
      toast.error(t("createDialog.nameRequired"));
      reset();
      return;
    }
    let created: InitiativeRead;
    try {
      created = await createInitiative.mutateAsync({
        name: trimmedName,
        description: description.trim() || undefined,
        color,
        join_policy: joinPolicy,
        // One `{plural}_enabled` field per tool, straight from the grid — every
        // tool is answered here, so there is no default to fall back to.
        ...(Object.fromEntries(
          TOOLS.map((tool) => [toolViewPermission(tool), Boolean(selected[tool])])
        ) as Partial<InitiativeCreate>),
      });
    } catch {
      // The create hook reports its own failure; there is nothing to configure.
      return;
    }
    // Awaited, not run from the create's success callback. A callback belongs
    // to this dialog being mounted, so closing the wizard — or navigating away
    // — while the create was still in flight used to drop the permissions
    // silently: the initiative arrived with a calendar its members could not
    // see, and nothing said so.
    try {
      await grantToMembers.mutateAsync({
        initiativeId: created.id,
        tools: chosenTools,
        audience,
      });
    } catch {
      // The initiative exists and is correct; only the widening failed, and
      // saying "could not create" about it would be false.
      toast.error(t("createWizard.memberGrantFailed"));
    }
    onOpenChange(false);
    onCreated?.(created);
  }, [
    trimmedName,
    description,
    color,
    joinPolicy,
    selected,
    chosenTools,
    audience,
    createInitiative,
    grantToMembers,
    onOpenChange,
    onCreated,
    reset,
    t,
  ]);

  // Back sits bottom-left and the way forward bottom-right, and the way
  // forward says where it goes: "Next" alone tells somebody nothing about how
  // much is left, and a first-timer is exactly the person who wants to know.
  const footer = (next: NextAction) => (
    <DialogFooter className="flex-row items-center justify-between sm:justify-between">
      {canGoBack ? (
        <WizardBackButton onClick={back} disabled={busy} label={t("createWizard.back")} />
      ) : (
        <span />
      )}
      <Button
        type={next.submit ? "submit" : "button"}
        onClick={next.onClick}
        disabled={next.disabled}
        pending={next.pending}
      >
        {next.label}
      </Button>
    </DialogFooter>
  );

  return (
    <WizardDialog
      open={open}
      onOpenChange={onOpenChange}
      className="max-h-screen overflow-y-auto bg-card sm:max-w-2xl"
      title={t("createWizard.title")}
      description={stepTitle}
      progress={{ current: STEP_ORDER.indexOf(step) + 1, total: STEP_ORDER.length }}
    >
      {step === "details" ? (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (trimmedName) go("tools");
          }}
        >
          {isFirst ? (
            // The community's first one: say what an initiative is before
            // asking what to call it. Nothing else has had the chance — and
            // Yonder is the one who does the explaining everywhere else, so
            // he does it here too.
            <div className="flex items-start gap-3 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
              <img
                src={yonderTalking}
                alt=""
                aria-hidden="true"
                className="-mt-1 h-14 w-14 shrink-0"
              />
              <div className="min-w-0 space-y-1">
                <p className="font-medium">{t("createWizard.firstIntroTitle")}</p>
                <Markdown
                  content={t("createWizard.firstIntro")}
                  className="text-muted-foreground text-sm"
                />
                <a
                  href={INITIATIVES_DOC_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block font-medium text-primary text-xs underline underline-offset-2"
                >
                  {t("createWizard.firstIntroLink")}
                </a>
              </div>
            </div>
          ) : null}
          <Field label={t("createDialog.nameLabel")}>
            <Input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={t("createDialog.namePlaceholder")}
              maxLength={255}
              required
            />
          </Field>
          <Field label={t("createDialog.descriptionLabel")}>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("createDialog.descriptionPlaceholder")}
              rows={3}
            />
          </Field>
          <Field label={t("createDialog.colorLabel")} hint={t("createDialog.colorHint")}>
            <ColorPickerPopover value={color} onChange={setColor} />
          </Field>
          {footer({ label: t("createWizard.nextTools"), disabled: !trimmedName, submit: true })}
        </form>
      ) : null}

      {step === "tools" ? (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("createWizard.toolsHelp")}</p>
          {/* The same grid the settings screen shows, so the picture
                somebody learned a tool from is the one they meet again later.
                No `roles` here: the initiative does not exist yet, so there is
                no audience to report. */}
          <ToolsSection
            layout="plain"
            idPrefix="create"
            canManage
            isSaving={false}
            values={selected as Partial<Record<Tool, boolean>>}
            onToggle={(tool, value) => setSelected((prev) => ({ ...prev, [tool]: value }))}
          />
          {/* Said out loud rather than left to a greyed-out button: an
                initiative with no tools has nowhere to put anything. */}
          {chosenTools.length === 0 ? (
            <p className="text-destructive text-xs">{t("createWizard.pickOneTool")}</p>
          ) : null}
          {footer({
            label: t("createWizard.nextJoining"),
            onClick: () => go("joining"),
            disabled: chosenTools.length === 0,
          })}
        </div>
      ) : null}

      {step === "joining" ? (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("createWizard.joiningHelp")}</p>
          <JoinPolicySection
            layout="plain"
            idPrefix="create"
            value={joinPolicy}
            onChange={setJoinPolicy}
            canManage
            isSaving={false}
          />
          {footer({ label: t("createWizard.nextMembers"), onClick: () => go("members") })}
        </div>
      ) : null}

      {step === "members" ? (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm">{t("createWizard.membersHelp")}</p>
          <RadioGroup
            value={audience}
            onValueChange={(value) => setAudience(value as MemberAudience)}
            className="space-y-2"
          >
            {MEMBER_AUDIENCES.map((value) => (
              <div key={value} className="flex items-start gap-3 rounded-lg border p-3">
                <RadioGroupItem value={value} id={`create-members-${value}`} className="mt-1" />
                <div className="space-y-0.5">
                  <Label htmlFor={`create-members-${value}`} className="font-medium">
                    {t(`createWizard.members.${value}` as never)}
                  </Label>
                  <p className="text-muted-foreground text-xs">
                    {t(`createWizard.members.${value}Help` as never)}
                  </p>
                </div>
              </div>
            ))}
          </RadioGroup>
          {footer({
            label: busy ? t("createDialog.creating") : t("createWizard.create"),
            onClick: handleSubmit,
            pending: busy,
          })}
        </div>
      ) : null}
    </WizardDialog>
  );
};

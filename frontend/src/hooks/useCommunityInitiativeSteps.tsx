import type { FlatNamespace } from "i18next";
import { Loader2, Zap } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Tool } from "@/api/generated/initiativeAPI.schemas";
import { CommunityAvatar } from "@/components/communities/CommunitySidebar";
import { useCommunities } from "@/hooks/useCommunities";
import {
  communityMayAuthorTools,
  communityMayWriteContent,
  useCreatableInitiatives,
} from "@/hooks/useInitiativeAccess";
import { useWizard } from "@/hooks/useWizard";
import { InitiativeColorDot } from "@/lib/initiativeColors";
import type { TranslateFn } from "@/types/i18n";
import { WizardOption } from "@/ui/wizard-dialog";

type Step = "select-community" | "select-initiative";

export interface Choice {
  id: number;
  name: string;
}

interface Options<Next extends string> {
  /** The wizard's own namespace, which holds its `createWizard.*` strings. */
  ns: FlatNamespace;
  open: boolean;
  /**
   * The tool the wizard creates: only communities it could be authored in are
   * offered, and only initiatives that allow it. Null for a wizard that writes
   * into existing content — a task in a project — which a `read_write` grant
   * may do, and where every live initiative is offered.
   */
  authors: Tool | null;
  /** The place last used, offered above the community list. */
  shortcut: { title: string; subtitle: string; onClick: () => void } | null;
  onInitiative?: (community: Choice, initiative: Choice) => void;
  /** The wizard's own step after these two, if it has one. */
  next?: { step: Next; description: string };
  /** Drawn at the end of each initiative's row. */
  initiativeIcon?: ReactNode;
}

/**
 * The first two steps of the global create wizards: a community, then an
 * initiative in it. `dialog` is what the `WizardDialog` takes of them, and
 * `body` is their content — null on the wizard's own step.
 *
 * A step with one answer, and no shortcut beside it, is walked past on its
 * own — once per opening, so Back to it stays there.
 */
export function useCommunityInitiativeSteps<Next extends string = never>({
  ns,
  open,
  authors,
  shortcut,
  onInitiative,
  next,
  initiativeIcon,
}: Options<Next>) {
  // A tool's wizard reads its tool's own namespace, so the loose translate
  // signature rather than the statically-typed one.
  const { t: translate } = useTranslation(ns);
  const t = translate as TranslateFn;
  const { communities: allCommunities } = useCommunities();
  const communities = useMemo(
    () => allCommunities.filter(authors ? communityMayAuthorTools : communityMayWriteContent),
    [allCommunities, authors]
  );

  const { step, go, back, canGoBack, reset } = useWizard<Step | Next>("select-community");
  const [community, setCommunity] = useState<Choice | null>(null);
  const [initiative, setInitiative] = useState<Choice | null>(null);
  const walkedPast = useRef(new Set<string>());

  useEffect(() => {
    if (!open) {
      reset();
      walkedPast.current.clear();
    }
  }, [open, reset]);

  const { initiatives, isLoading } = useCreatableInitiatives(
    authors,
    step === "select-community" ? null : (community?.id ?? null)
  );

  const chooseCommunity = useCallback(
    (choice: Choice) => {
      setCommunity(choice);
      go("select-initiative");
    },
    [go]
  );

  const nextStep = next?.step;
  const chooseInitiative = useCallback(
    (choice: Choice) => {
      if (!community) return;
      setInitiative(choice);
      onInitiative?.(community, choice);
      if (nextStep) go(nextStep);
    },
    [community, onInitiative, nextStep, go]
  );

  // Somebody with one community and no shortcut never sees the first step,
  // so it is not one of the steps they walk.
  const skipsCommunityStep = communities.length === 1 && !shortcut;
  useEffect(() => {
    if (!open || walkedPast.current.has(step)) return;
    if (step === "select-community" && skipsCommunityStep) {
      walkedPast.current.add(step);
      chooseCommunity(communities[0]);
    } else if (step === "select-initiative" && !isLoading && initiatives.length === 1) {
      walkedPast.current.add(step);
      chooseInitiative(initiatives[0]);
    }
  }, [
    open,
    step,
    skipsCommunityStep,
    communities,
    isLoading,
    initiatives,
    chooseCommunity,
    chooseInitiative,
  ]);

  const walked: string[] = [
    ...(skipsCommunityStep ? [] : ["select-community"]),
    "select-initiative",
    ...(nextStep ? [nextStep] : []),
  ];
  // The frame before a step is walked past still shows it, and a step outside
  // the count has no position to state.
  const position = walked.indexOf(step);

  const dialog = {
    title: t("createWizard.title"),
    description:
      step === "select-community"
        ? t("createWizard.selectCommunity")
        : step === "select-initiative"
          ? t("createWizard.selectInitiative")
          : next?.description,
    progress:
      position < 0 || walked.length < 2
        ? undefined
        : { current: position + 1, total: walked.length },
    onBack: canGoBack ? back : undefined,
    backLabel: t("createWizard.back"),
  };

  const body =
    step === "select-community" ? (
      <div className="space-y-2">
        {shortcut && (
          <WizardOption
            className="border-primary/30 bg-primary/5 hover:bg-primary/10"
            icon={<Zap className="h-5 w-5 shrink-0 text-primary" />}
            title={shortcut.title}
            description={shortcut.subtitle}
            onClick={shortcut.onClick}
          >
            <span className="text-muted-foreground text-xs">{t("createWizard.lastUsed")}</span>
          </WizardOption>
        )}
        {communities.map((entry) => (
          <WizardOption
            key={entry.id}
            icon={
              <CommunityAvatar name={entry.name} icon={entry.icon_url} active={false} size="sm" />
            }
            title={entry.name}
            onClick={() => chooseCommunity(entry)}
          />
        ))}
      </div>
    ) : step === "select-initiative" ? (
      <div className="space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : initiatives.length === 0 ? (
          <p className="py-4 text-center text-muted-foreground text-sm">
            {t("createWizard.noInitiatives")}
          </p>
        ) : (
          initiatives.map((entry) => (
            <WizardOption
              key={entry.id}
              icon={<InitiativeColorDot color={entry.color} />}
              title={entry.name}
              onClick={() => chooseInitiative(entry)}
            >
              {initiativeIcon}
            </WizardOption>
          ))
        )}
      </div>
    ) : null;

  return { step, community, initiative, dialog, body };
}

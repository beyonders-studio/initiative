/**
 * The chrome a multi-step dialog shares: the frame, the heading, where you are,
 * the way back, and the cards a step's choices are drawn as.
 *
 * It holds no strings and no opinion about size. Both are deliberate. The
 * dialogs that use this disagree about width and scrolling — a two-question
 * picker and a four-question form are not the same shape — so `className` goes
 * straight through. And the back label stays the caller's, because each of
 * these already has its own key for it and the translations do not all agree;
 * a default here would quietly reword five dialogs.
 *
 * Pair it with {@link useWizard}, which owns which step is showing.
 */

import { ChevronLeft } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/ui/dialog";
import { cn } from "@/ui/lib/utils";

export interface WizardBackButtonProps
  extends Omit<ComponentProps<typeof Button>, "children" | "variant" | "size" | "type"> {
  /** What the button says. The caller's, not ours — see the note above. */
  label: string;
}

/**
 * Exported on its own because one wizard puts Back in a footer opposite its
 * forward button rather than above the body, and that layout is its own
 * decision to make.
 */
export const WizardBackButton = ({ label, ...props }: WizardBackButtonProps) => (
  <Button type="button" variant="ghost" size="sm" {...props}>
    <ChevronLeft className="h-4 w-4" />
    {label}
  </Button>
);

export interface WizardProgress {
  /** 1-based. */
  current: number;
  total: number;
}

/**
 * How far along, as dots plus a line of text only a screen reader gets.
 *
 * The dots are marked decorative: you cannot jump to a step by clicking one,
 * so there is nothing here to tab to or to announce as a control. The position
 * is carried by the text beside them, which is live — a dialog that swaps its
 * description as you move otherwise tells you nothing about having moved.
 */
const WizardProgressDots = ({ current, total }: WizardProgress) => {
  const { t } = useTranslation("ui");
  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1.5" aria-hidden="true">
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className={cn(
              "h-1.5 rounded-full transition-all",
              index + 1 === current ? "w-4 bg-primary" : "w-1.5 bg-muted-foreground/30"
            )}
          />
        ))}
      </div>
      <span aria-live="polite" className="sr-only">
        {t("wizard.stepOf", { current, total })}
      </span>
    </div>
  );
};

export interface WizardFrameProps {
  title: ReactNode;
  /** The per-step orientation line. Falsy renders no description at all. */
  description?: ReactNode;
  /** Omit where there is no position worth stating — one step, or a step
   *  arrived at and not left. */
  progress?: WizardProgress;
  /** Omit to render no back row: a first step, a step with no way out, or a
   *  wizard that draws Back somewhere else. */
  onBack?: () => void;
  backLabel?: string;
  backDisabled?: boolean;
  /** Inside a dialog the heading is the dialog's own title and description;
   *  on a page it is the page's heading. */
  inDialog?: boolean;
  children: ReactNode;
}

/**
 * The heading, the dots and the way back, without the dialog around them, for
 * a wizard that is a page of its own. Rendered as siblings, so the container
 * decides the spacing between them.
 */
export const WizardFrame = ({
  title,
  description,
  progress,
  onBack,
  backLabel,
  backDisabled,
  inDialog = false,
  children,
}: WizardFrameProps) => (
  <>
    <DialogHeader>
      {inDialog ? (
        <DialogTitle>{title}</DialogTitle>
      ) : (
        <h1 className="font-semibold text-lg leading-none">{title}</h1>
      )}
      {description ? (
        inDialog ? (
          <DialogDescription>{description}</DialogDescription>
        ) : (
          <p className="text-muted-foreground text-sm">{description}</p>
        )
      ) : null}
    </DialogHeader>
    {progress ? <WizardProgressDots {...progress} /> : null}
    {onBack ? (
      <WizardBackButton
        className="w-fit"
        onClick={onBack}
        disabled={backDisabled}
        label={backLabel ?? ""}
      />
    ) : null}
    {children}
  </>
);

/**
 * Below `sm` a wizard takes the whole screen: a centred box with a margin
 * round it leaves a phone's keyboard covering the field being typed in. The
 * caller's own classes still decide the size above it.
 */
const FULL_SCREEN_BELOW_SM =
  "max-sm:inset-0 max-sm:h-dvh max-sm:max-h-none max-sm:max-w-none max-sm:translate-x-0 max-sm:translate-y-0 max-sm:content-start max-sm:overflow-y-auto max-sm:rounded-none max-sm:border-0 max-sm:pb-[max(1.5rem,env(safe-area-inset-bottom))]";

export interface WizardDialogProps extends Omit<WizardFrameProps, "inDialog"> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Straight onto `DialogContent`. */
  className?: string;
}

export const WizardDialog = ({ open, onOpenChange, className, ...frame }: WizardDialogProps) => (
  <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent className={cn(FULL_SCREEN_BELOW_SM, className)}>
      <WizardFrame inDialog {...frame} />
    </DialogContent>
  </Dialog>
);

export interface WizardOptionProps extends Omit<ComponentProps<"button">, "title" | "type"> {
  /** What leads the card: an icon, a mark, an avatar. */
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
}

/**
 * One of the choices a wizard step offers, as a card: the icon, then the title
 * over its description. Anything passed as children follows the text.
 */
export const WizardOption = ({
  icon,
  title,
  description,
  className,
  children,
  ...props
}: WizardOptionProps) => (
  <button
    type="button"
    className={cn(
      "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-transparent",
      className
    )}
    {...props}
  >
    {icon}
    <span className="min-w-0 flex-1">
      <span className="block font-medium text-sm">{title}</span>
      {description ? (
        <span className="block text-muted-foreground text-xs">{description}</span>
      ) : null}
    </span>
    {children}
  </button>
);

import { useTranslation } from "react-i18next";

import { PATH_SCENES, PATH_TINTS, PixelScene } from "@/components/start/PixelScene";
import { ContinueButton } from "@/components/start/stepParts";
import type { StartPath } from "@/lib/startFlow";
import { Label } from "@/ui/label";
import { cn } from "@/ui/lib/utils";
import { RadioGroup, RadioGroupItem } from "@/ui/radio-group";

/** The paths this deployment offers, as one card each with a picture and an
 *  example of who it suits. */
export const ChooseStep = ({
  paths,
  value,
  onChange,
  onContinue,
  disabled,
}: {
  paths: StartPath[];
  value: StartPath;
  onChange: (path: StartPath) => void;
  onContinue: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  return (
    <>
      <RadioGroup
        value={value}
        onValueChange={(next) => onChange(next as StartPath)}
        className="gap-3"
      >
        {paths.map((path) => (
          <Label
            key={path}
            htmlFor={`start-path-${path}`}
            className="group flex cursor-pointer items-center gap-3 rounded-xl border-2 bg-card p-3 font-normal transition-colors hover:border-primary/40 has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-primary/5 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring sm:gap-4"
          >
            <span
              className={cn(
                "grid size-16 shrink-0 place-items-center rounded-lg sm:size-20",
                PATH_TINTS[path]
              )}
            >
              <PixelScene
                scene={PATH_SCENES[path]}
                className="w-11 group-has-[[data-state=checked]]:motion-safe:animate-[yonder-hop_0.4s_ease-out] sm:w-14"
              />
            </span>
            <span className="min-w-0 flex-1 space-y-1">
              <span className="block font-semibold">{t(`start.choose.${path}`)}</span>
              <span className="block text-muted-foreground text-sm">
                {t(`start.choose.${path}Hint`)}
              </span>
              <span className="block text-muted-foreground text-xs italic">
                {t(`start.choose.${path}Example`)}
              </span>
            </span>
            <RadioGroupItem id={`start-path-${path}`} value={path} className="self-start" />
          </Label>
        ))}
      </RadioGroup>
      <ContinueButton onClick={onContinue} disabled={disabled} />
    </>
  );
};

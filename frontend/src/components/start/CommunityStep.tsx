import { useTranslation } from "react-i18next";

import { ContinueButton, StepField } from "@/components/start/stepParts";
import type { StartAnswers } from "@/lib/startFlow";
import { Input } from "@/ui/input";
import { Textarea } from "@/ui/textarea";

/** The names a new community starts with: a space and its first list for
 *  Personal, a community and its first initiative for Shared. */
export const CommunityStep = ({
  path,
  answers,
  update,
  onContinue,
  disabled,
}: {
  path: "personal" | "shared";
  answers: StartAnswers;
  update: (patch: Partial<StartAnswers>) => void;
  onContinue: () => void;
  disabled?: boolean;
}) => {
  const { t } = useTranslation("auth");
  return (
    <>
      <StepField id="start-community-name" label={t(`start.${path}.nameLabel`)}>
        <Input
          id="start-community-name"
          value={answers.communityName}
          onChange={(event) => update({ communityName: event.target.value })}
          maxLength={255}
        />
      </StepField>
      {path === "personal" ? (
        <StepField id="start-list-name" label={t("start.personal.listLabel")}>
          <Input
            id="start-list-name"
            value={answers.listName}
            onChange={(event) => update({ listName: event.target.value })}
            maxLength={255}
          />
        </StepField>
      ) : (
        <>
          <StepField id="start-description" label={t("start.shared.descriptionLabel")}>
            <Textarea
              id="start-description"
              value={answers.description}
              onChange={(event) => update({ description: event.target.value })}
              rows={3}
            />
          </StepField>
          <StepField
            id="start-initiative-name"
            label={t("start.shared.initiativeLabel")}
            hint={t("start.shared.initiativeHint")}
          >
            <Input
              id="start-initiative-name"
              value={answers.initiativeName}
              onChange={(event) => update({ initiativeName: event.target.value })}
              maxLength={255}
            />
          </StepField>
        </>
      )}
      <ContinueButton onClick={onContinue} disabled={disabled} />
    </>
  );
};

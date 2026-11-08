import { useTranslation } from "react-i18next";

import { ContinueButton } from "@/components/start/stepParts";
import type { StartAnswers } from "@/lib/startFlow";
import { Field } from "@/ui/field";
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
      <Field label={t(`start.${path}.nameLabel`)}>
        <Input
          value={answers.communityName}
          onChange={(event) => update({ communityName: event.target.value })}
          maxLength={255}
        />
      </Field>
      {path === "personal" ? (
        <Field label={t("start.personal.listLabel")}>
          <Input
            value={answers.listName}
            onChange={(event) => update({ listName: event.target.value })}
            maxLength={255}
          />
        </Field>
      ) : (
        <>
          <Field label={t("start.shared.descriptionLabel")}>
            <Textarea
              value={answers.description}
              onChange={(event) => update({ description: event.target.value })}
              rows={3}
            />
          </Field>
          <Field label={t("start.shared.initiativeLabel")} hint={t("start.shared.initiativeHint")}>
            <Input
              value={answers.initiativeName}
              onChange={(event) => update({ initiativeName: event.target.value })}
              maxLength={255}
            />
          </Field>
        </>
      )}
      <ContinueButton onClick={onContinue} disabled={disabled} />
    </>
  );
};

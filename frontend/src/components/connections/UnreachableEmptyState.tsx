import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { BirthdateField } from "@/components/auth/BirthdateField";
import { useAgeConfirmation } from "@/components/auth/useAgeConfirmation";
import { Button } from "@/components/ui/button";
import { useUpdateDmSettings } from "@/hooks/useDirectMessages";

/**
 * Why nothing is listed, in the order the reasons outrank one another.
 *
 * `age` first and alone: an account that has not answered has no policy worth
 * offering and no connections to fall back on, so the panel below it would be
 * pointing at a route that cannot work.
 */
export type UnreachableReason = "age" | "private" | null;

export const unreachableReason = (
  ageConfirmed: boolean,
  policy: string | undefined
): UnreachableReason => {
  if (!ageConfirmed) return "age";
  if (policy === "private") return "private";
  return null;
};

/**
 * The question itself, wherever it is asked.
 *
 * Its own component because the answer unlocks direct messages everywhere and
 * more than one surface has to be able to take it — the Privacy tab that
 * states the rule, and any page whose whole content the unanswered question
 * holds back. A page that only said "you cannot use this yet" and left the
 * form somewhere else would be a lock with the key in another room.
 *
 * `id` because two of these can share a page, and a label points at exactly
 * one field.
 */
export const AgeConfirmationForm = ({ id }: { id: string }) => {
  const { t } = useTranslation(["connections", "settings"]);
  const { birthdate, setBirthdate, submitting, error, confirm } = useAgeConfirmation();

  return (
    <form
      className="max-w-sm space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        void confirm();
      }}
    >
      <BirthdateField id={id} value={birthdate} onChange={setBirthdate} disabled={submitting} />
      {error && <p className="text-destructive text-sm">{error}</p>}
      <Button type="submit" size="sm" disabled={submitting}>
        {t("settings:privacy.dm.confirmAge")}
      </Button>
    </form>
  );
};

/**
 * The panel above the page for an account that has not said how old it is.
 *
 * It states the rule and the fact and stops there. What is on the other side
 * of the answer is deliberately not sold: this is a checkbox about a birthday,
 * and the only thing keeping the answer honest is that nothing here gave a
 * reason to get it wrong.
 */
export const AgeUnansweredPanel = ({ id = "connections-age" }: { id?: string } = {}) => {
  // The rule and the fact are the Privacy tab's own words: two surfaces say
  // the same thing to the same account, and one string keeps them agreeing.
  const { t } = useTranslation(["connections", "settings"]);

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div className="space-y-1">
        <h2 className="font-medium text-sm">{t("unreachable.age.title")}</h2>
        <p className="max-w-prose text-muted-foreground text-sm">
          {t("settings:privacy.dm.ageLocked")}
        </p>
      </div>
      <AgeConfirmationForm id={id} />
    </section>
  );
};

/**
 * The panel for an account that is reachable by nobody because it chose to be.
 *
 * Two ways out, and the sentence is the more important of them: a connection
 * reaches this account whatever its policy, so somebody who means to stay
 * closed should leave knowing the feature works rather than thinking it broke.
 * The button is the other, and it writes the one value that changes who may
 * ask.
 */
export const PrivatePanel = () => {
  const { t } = useTranslation("connections");
  const updateSettings = useUpdateDmSettings();

  return (
    <section className="space-y-3 rounded-lg border border-dashed p-4">
      <p className="max-w-prose text-muted-foreground text-sm">{t("unreachable.private.body")}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={updateSettings.isPending}
          // The policy alone. Sending the community switches with it would
          // stake the whole write on a membership list the page fetched
          // earlier: leaving a community between the two makes the server
          // refuse the unknown id, and the account that clicked "let my
          // communities message me" stays Private. Every community counts by
          // default, so a switch is only off where its owner turned it off,
          // and that is theirs to keep — the link beside this is where they
          // are changed.
          onClick={() => updateSettings.mutate({ data: { dm_policy: "community" } })}
        >
          {t("unreachable.private.open")}
        </Button>
        <Button type="button" size="sm" variant="outline" asChild>
          <Link to="/profile/privacy">{t("unreachable.private.settings")}</Link>
        </Button>
      </div>
    </section>
  );
};

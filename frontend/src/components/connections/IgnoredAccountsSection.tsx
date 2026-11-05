import { useTranslation } from "react-i18next";

import { HandleField } from "@/components/connections/HandleField";
import { PersonRow } from "@/components/connections/PersonRow";
import { Button } from "@/components/ui/button";
import {
  useIgnoreAccountByHandle,
  useIgnoredAccounts,
  useStopIgnoring,
} from "@/hooks/useDirectMessages";

/** The accounts this person has chosen not to hear from. */
export const IgnoredAccountsSection = () => {
  const { t } = useTranslation("settings");
  const { data } = useIgnoredAccounts();
  const ignoreByHandle = useIgnoreAccountByHandle();
  const stopIgnoring = useStopIgnoring();

  const items = data?.items ?? [];

  return (
    <div className="space-y-3">
      <HandleField
        label={t("privacy.ignored.add")}
        placeholder={t("privacy.connections.addPlaceholder")}
        hint={t("privacy.connections.addHint")}
        submitLabel={t("privacy.ignored.ignore")}
        errorFallback="errors:DM_USER_NOT_FOUND"
        pending={ignoreByHandle.isPending}
        onSubmit={(handle) => ignoreByHandle.mutateAsync({ data: handle })}
      />
      {items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("privacy.ignored.empty")}</p>
      ) : (
        <ul className="divide-y">
          {items.map((account) => (
            <PersonRow
              key={account.user_id}
              user={{
                id: account.user_id,
                username: account.username,
                discriminator: account.discriminator,
                avatar_url: account.avatar_url,
              }}
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => stopIgnoring.mutate({ userId: account.user_id })}
                disabled={stopIgnoring.isPending}
              >
                {t("privacy.ignored.stop")}
              </Button>
            </PersonRow>
          ))}
        </ul>
      )}
    </div>
  );
};

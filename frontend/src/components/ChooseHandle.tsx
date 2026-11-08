import { useState } from "react";
import { useTranslation } from "react-i18next";

import { claimMyUsername } from "@/api/generated/users/users";
import { type HandleCheck, UsernameField } from "@/components/UsernameField";
import { useAuth } from "@/hooks/useAuth";
import { getErrorMessage } from "@/lib/errorMessage";
import { Button } from "@/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/ui/card";

/**
 * The screen an account meets when it was handed a handle rather than picking
 * one — provisioned from single sign-on, or carried over from before handles
 * existed. It blocks the app until they choose, because the handle is how
 * everyone else will see them.
 */
export const ChooseHandle = () => {
  const { t } = useTranslation(["auth", "common"]);
  const { user, refreshUser } = useAuth();
  const [username, setUsername] = useState("");
  const [handle, setHandle] = useState<HandleCheck>({ usable: true, offer: null });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const suggestion = user?.username ?? "";

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await claimMyUsername({
        username: username.trim().toLowerCase(),
        offer: handle.offer ?? undefined,
      });
      await refreshUser();
    } catch (err) {
      setError(getErrorMessage(err, "auth:chooseHandle.error"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-app items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>{t("chooseHandle.title")}</CardTitle>
          <CardDescription>{t("chooseHandle.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <UsernameField
              id="choose-handle"
              value={username}
              onChange={setUsername}
              suggestion={suggestion}
              onChecked={setHandle}
              disabled={submitting}
            />
            {error && <p className="text-destructive text-sm">{error}</p>}
            <Button
              type="submit"
              className="w-full"
              disabled={submitting || !username.trim() || !handle.usable}
            >
              {submitting ? t("common:submitting") : t("chooseHandle.submit")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
};

import { useTranslation } from "react-i18next";

import { formatDate } from "@/ui/lib/formatDate";
import { cn } from "@/ui/lib/utils";

/**
 * When the account was made — the one fact a profile states about the account
 * rather than about the person.
 *
 * It sits at the far end of the row the picture leads, out of the way: how
 * someone is appearing is a badge on the picture itself now, so the space
 * under it belongs to the trophies and to what they are part of.
 */
export const ProfileJoined = ({
  joinedAt,
  className,
}: {
  joinedAt: string;
  className?: string;
}) => {
  const { t } = useTranslation("profiles");
  return (
    <dl className={cn("flex items-center gap-2 text-sm", className)}>
      <dt className="text-muted-foreground">{t("joined.label")}</dt>
      <dd className="font-medium">{formatDate(joinedAt)}</dd>
    </dl>
  );
};

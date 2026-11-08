import { useTranslation } from "react-i18next";

import { FilerState } from "@/api/generated/initiativeAPI.schemas";
import { Badge } from "@/ui/badge";

const VARIANT: Record<FilerState, "default" | "secondary" | "outline"> = {
  [FilerState.received]: "outline",
  [FilerState.in_progress]: "secondary",
  // The one state that asks something of the reader stands out.
  [FilerState.waiting_on_you]: "default",
  [FilerState.closed]: "outline",
};

/** Where a ticket stands, as the person who filed it is shown it. */
export const TicketStateBadge = ({ state }: { state: FilerState }) => {
  const { t } = useTranslation("intake");
  return (
    <Badge variant={VARIANT[state]} className="whitespace-nowrap">
      {t(`tickets.state.${state}`)}
    </Badge>
  );
};

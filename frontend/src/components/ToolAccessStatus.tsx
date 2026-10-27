import { AlertCircle, SearchX, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SearchEntityType } from "@/api/generated/initiativeAPI.schemas";
import { NeedAccessOr } from "@/components/access/RequestAccess";
import { StatusMessage } from "@/components/StatusMessage";
import { getErrorMessage, getHttpStatus } from "@/lib/errorMessage";

/** Where a detail page keeps its `noAccess` and `notFound` strings, each with
 *  a `…Description` beside it. */
type AccessKeys =
  | "calendars:"
  | "counterGroups:"
  | "dashboards:"
  | "files:collections."
  | "files:detail."
  | "posts:"
  | "projects:detail."
  | "queues:"
  | "tasks:edit."
  | "wikis:";

interface ToolAccessStatusProps {
  /** The failed read — or nothing, when there was no valid id to read. */
  error: unknown;
  keys: AccessKeys;
  backTo: string;
  backLabel: string;
  /** What the page was reading. Given, a reader who knows it is there and
   *  cannot open it is offered a way to ask for access. */
  entity?: { kind: SearchEntityType; id: number };
}

/**
 * What a detail page shows in place of the thing it could not read: no access
 * on a 403, not found on a 404 or when there was nothing to ask for, and the
 * error itself for anything else — a failed request is not a missing item.
 *
 * Either refusal may be something the reader can ask for: when the standing
 * read says they cannot open it, the way to ask takes the message's place.
 * When that read finds nothing, the page says what it always said.
 */
export function ToolAccessStatus({ entity, ...props }: ToolAccessStatusProps) {
  return (
    <NeedAccessOr
      error={props.error}
      entity={entity}
      backTo={props.backTo}
      backLabel={props.backLabel}
    >
      <Refusal {...props} />
    </NeedAccessOr>
  );
}

function Refusal({ error, keys, backTo, backLabel }: Omit<ToolAccessStatusProps, "entity">) {
  const { t } = useTranslation();
  const status = getHttpStatus(error);

  if (error && status !== 403 && status !== 404) {
    return (
      <StatusMessage
        icon={<AlertCircle />}
        title={getErrorMessage(error)}
        backTo={backTo}
        backLabel={backLabel}
      />
    );
  }

  const denied = status === 403;
  const key = denied ? "noAccess" : "notFound";
  // Every namespace `keys` names carries both pairs, and the page has loaded it.
  return (
    <StatusMessage
      icon={denied ? <ShieldAlert /> : <SearchX />}
      title={t(`${keys}${key}` as never)}
      description={t(`${keys}${key}Description` as never)}
      backTo={backTo}
      backLabel={backLabel}
    />
  );
}

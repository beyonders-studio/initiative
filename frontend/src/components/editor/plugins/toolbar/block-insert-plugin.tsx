import { PlusIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  type InsertAction,
  useBlockInsertActions,
} from "@/components/editor/plugins/toolbar/toolbar-actions";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "@/ui/select";

/** The insert picker: pictures, tables, embeds and the rest. */
export function BlockInsertPlugin(props: { rich: boolean; hostActions: readonly InsertAction[] }) {
  const { t } = useTranslation("editor");
  const actions = useBlockInsertActions(props);

  return (
    <Select value="">
      <SelectTrigger className="h-8! w-min gap-1">
        <PlusIcon className="size-4" />
        <span>{t("insert")}</span>
      </SelectTrigger>
      <SelectContent>
        <SelectGroup>
          {actions.map((action) => (
            <SelectItem key={action.id} value={action.id} onPointerUp={action.run}>
              <div className="flex items-center gap-1">
                {action.icon}
                <span>{action.label}</span>
              </div>
            </SelectItem>
          ))}
        </SelectGroup>
      </SelectContent>
    </Select>
  );
}

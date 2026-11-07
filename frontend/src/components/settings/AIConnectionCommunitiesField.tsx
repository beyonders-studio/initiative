/**
 * The communities an operator's connection serves. Given some, it serves only
 * them, on its own key; given none, it serves every community no other
 * connection is given to. A community given here leaves any other connection
 * it was given to.
 */

import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AIConnectionCommunity } from "@/api/generated/initiativeAPI.schemas";
import { usePlatformCommunities } from "@/hooks/useSettings";
import { AsyncCombobox } from "@/ui/async-combobox";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Label } from "@/ui/label";

interface AIConnectionCommunitiesFieldProps {
  communities: AIConnectionCommunity[];
  onChange: (communities: AIConnectionCommunity[]) => void;
}

export const AIConnectionCommunitiesField = ({
  communities,
  onChange,
}: AIConnectionCommunitiesFieldProps) => {
  const { t } = useTranslation("settings");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [search, setSearch] = useState("");
  const listed = usePlatformCommunities(
    { search: search || null, page_size: 20 },
    { enabled: pickerOpen }
  );
  const given = new Set(communities.map((community) => community.id));
  const items = (listed.data?.items ?? [])
    .filter((row) => !given.has(row.id))
    .map((row) => ({ value: String(row.id), label: row.name }));

  return (
    <div className="space-y-2">
      <Label>{t("aiConnections.communitiesLabel")}</Label>
      {communities.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {communities.map((community) => {
            const name = community.name ?? t("aiConnections.goneCommunity", { id: community.id });
            return (
              <Badge key={community.id} variant="secondary">
                {name}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-4 w-4"
                  aria-label={t("aiConnections.removeCommunity", { name })}
                  onClick={() => onChange(communities.filter((c) => c.id !== community.id))}
                >
                  <X className="h-3 w-3" />
                </Button>
              </Badge>
            );
          })}
        </div>
      )}
      <AsyncCombobox
        aria-label={t("aiConnections.communitiesLabel")}
        items={items}
        value={null}
        onValueChange={(value) => {
          const picked = listed.data?.items.find((row) => String(row.id) === value);
          if (picked) onChange([...communities, { id: picked.id, name: picked.name }]);
        }}
        onSearchChange={setSearch}
        onOpenChange={setPickerOpen}
        loading={listed.isLoading}
        placeholder={t("aiConnections.communitiesPlaceholder")}
        searchPlaceholder={t("aiConnections.communitiesSearch")}
        emptyMessage={t("aiConnections.communitiesEmpty")}
      />
      <p className="text-muted-foreground text-xs">
        {communities.length > 0
          ? t("aiConnections.communitiesHelpGiven")
          : t("aiConnections.communitiesHelpNone")}
      </p>
    </div>
  );
};

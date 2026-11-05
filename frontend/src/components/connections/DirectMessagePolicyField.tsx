import { useTranslation } from "react-i18next";

import type { CommunityDmToggle, DmPolicy } from "@/api/generated/initiativeAPI.schemas";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";

interface DirectMessagePolicyFieldProps {
  policy: DmPolicy;
  communities: CommunityDmToggle[];
  /** Locked until the account has answered the age question. */
  disabled?: boolean;
  onPolicyChange: (policy: DmPolicy) => void;
  onCommunityChange: (communityId: number, enabled: boolean) => void;
}

/**
 * Who may ask to message this account, outside its connections.
 *
 * The heading scopes the whole group, so each option says only the one thing
 * that differs between them: a connection satisfies every value, which makes
 * it a property of the setting rather than of any option in it. That is also
 * what lets "Private" read as "No one" without being a lie.
 */
export const DirectMessagePolicyField = ({
  policy,
  communities,
  disabled = false,
  onPolicyChange,
  onCommunityChange,
}: DirectMessagePolicyFieldProps) => {
  const { t } = useTranslation("settings");
  const options: { value: DmPolicy; label: string; hint: string }[] = [
    { value: "private", label: t("privacy.dm.private"), hint: t("privacy.dm.privateHint") },
    { value: "community", label: t("privacy.dm.community"), hint: t("privacy.dm.communityHint") },
    { value: "public", label: t("privacy.dm.public"), hint: t("privacy.dm.publicHint") },
  ];

  return (
    <div className="space-y-4">
      <RadioGroup
        value={policy}
        onValueChange={(next) => onPolicyChange(next as DmPolicy)}
        disabled={disabled}
        className="space-y-2"
      >
        {options.map((option) => (
          <div key={option.value} className="flex items-start gap-3">
            <RadioGroupItem
              value={option.value}
              id={`dm-policy-${option.value}`}
              className="mt-1"
            />
            <Label htmlFor={`dm-policy-${option.value}`} className="font-normal leading-tight">
              <span className="block font-medium">{option.label}</span>
              <span className="block text-muted-foreground text-sm">{option.hint}</span>
            </Label>
          </div>
        ))}
      </RadioGroup>

      {/* Only meaningful under `community`, and only worth showing if there is
          more than nowhere to be reachable. */}
      {policy === "community" && communities.length > 0 && (
        <div className="space-y-3 border-t pt-4">
          <div>
            <p className="font-medium text-sm">{t("privacy.dm.communitiesTitle")}</p>
            <p className="text-muted-foreground text-sm">{t("privacy.dm.communitiesHint")}</p>
          </div>
          <ul className="space-y-2">
            {communities.map((community) => (
              <li key={community.community_id} className="flex items-center justify-between gap-4">
                <Label
                  htmlFor={`dm-community-${community.community_id}`}
                  className="font-normal text-sm"
                >
                  {community.name}
                </Label>
                <Switch
                  id={`dm-community-${community.community_id}`}
                  checked={community.enabled}
                  disabled={disabled}
                  onCheckedChange={(next) => onCommunityChange(community.community_id, next)}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

import { SettingsSection } from "@/components/settings/SettingsSection";
import { TrashTable } from "@/components/trash/TrashTable";
import { RetentionSetting } from "@/pages/community/settings/RetentionSetting";

export const TrashPage = () => (
  // The whole community settings section is admin-gated by CommunitySettingsLayout, so
  // this is always the admin "everything in the community" view. Members manage
  // their own deletions on the personal trash page (/profile/trash).
  <SettingsSection>
    <RetentionSetting />
    <TrashTable variant="community" showPurgeAction />
  </SettingsSection>
);

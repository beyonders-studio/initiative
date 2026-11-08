import { useTranslation } from "react-i18next";

import type { ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";
import { ShareControl } from "@/components/access/ShareControl";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/ui/accordion";

export interface CreateAccessSectionProps {
  initiativeId: number | null;
  /** Full grant list for the resource being created. */
  grants: ResourceGrantSchema[];
  /** Called with the updated grant list to persist in the dialog's state. */
  onChange: (grants: ResourceGrantSchema[]) => void;
  /**
   * Whether the "Advanced options" accordion starts expanded. Defaults to
   * `true`; every create dialog opens it by default except the file dialog.
   */
  defaultOpen?: boolean;
}

/**
 * The shared "Advanced options" access block used by every create dialog: an
 * accordion wrapping the {@link ShareControl} grant editor. Kept byte-equal to
 * the block each dialog previously inlined.
 */
export const CreateAccessSection = ({
  initiativeId,
  grants,
  onChange,
  defaultOpen = true,
}: CreateAccessSectionProps) => {
  const { t } = useTranslation("common");

  return (
    <Accordion type="single" collapsible defaultValue={defaultOpen ? "advanced" : undefined}>
      <AccordionItem value="advanced" className="border-b-0">
        <AccordionTrigger>{t("createAccess.advancedOptions")}</AccordionTrigger>
        <AccordionContent>
          <ShareControl initiativeId={initiativeId} grants={grants} onChange={onChange} />
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
};

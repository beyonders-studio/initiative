import {
  AlignLeft,
  Badge,
  Banknote,
  Braces,
  CalendarClock,
  CalendarDays,
  CircleCheck,
  Gauge,
  Hash,
  Link2,
  Link as LinkIcon,
  List,
  ListChecks,
  type LucideIcon,
  User,
} from "lucide-react";

import { MetadataType } from "@/api/generated/initiativeAPI.schemas";

export const PROPERTY_TYPE_ICONS: Record<MetadataType, LucideIcon> = {
  [MetadataType.text]: AlignLeft,
  [MetadataType.number]: Hash,
  [MetadataType.checkbox]: CircleCheck,
  [MetadataType.date]: CalendarDays,
  [MetadataType.datetime]: CalendarClock,
  [MetadataType.url]: LinkIcon,
  [MetadataType.select]: List,
  [MetadataType.multi_select]: ListChecks,
  [MetadataType.user_reference]: User,
  [MetadataType.currency]: Banknote,
  [MetadataType.scale]: Gauge,
  [MetadataType.link]: Link2,
  [MetadataType.badge]: Badge,
  [MetadataType.json]: Braces,
};

export const iconForPropertyType = (type: MetadataType): LucideIcon =>
  PROPERTY_TYPE_ICONS[type] ?? AlignLeft;

import {
  AlignLeft,
  Banknote,
  CalendarClock,
  CalendarDays,
  CircleCheck,
  Hash,
  Link as LinkIcon,
  List,
  ListChecks,
  type LucideIcon,
  Star,
  User,
} from "lucide-react";

import { PropertyType } from "@/api/generated/initiativeAPI.schemas";

export const PROPERTY_TYPE_ICONS: Record<PropertyType, LucideIcon> = {
  [PropertyType.text]: AlignLeft,
  [PropertyType.number]: Hash,
  [PropertyType.checkbox]: CircleCheck,
  [PropertyType.date]: CalendarDays,
  [PropertyType.datetime]: CalendarClock,
  [PropertyType.url]: LinkIcon,
  [PropertyType.select]: List,
  [PropertyType.multi_select]: ListChecks,
  [PropertyType.user_reference]: User,
  [PropertyType.currency]: Banknote,
  [PropertyType.rating]: Star,
};

export const iconForPropertyType = (type: PropertyType): LucideIcon =>
  PROPERTY_TYPE_ICONS[type] ?? AlignLeft;

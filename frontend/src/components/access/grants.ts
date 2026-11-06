import type { ResourceGrantSchema } from "@/api/generated/initiativeAPI.schemas";

/**
 * Default access grants for a newly created resource: every initiative member
 * gets read access. Seeds the {@link ShareControl} in all create dialogs
 * (project, counter group, calendar event, file).
 *
 * This is a shared template — spread it (`[...DEFAULT_GRANTS]`) at each use site
 * (initial state and reset-on-close) so every dialog owns an independent array
 * and can never mutate a reference shared with another dialog.
 */
export const DEFAULT_GRANTS: ResourceGrantSchema[] = [
  { all_initiative_members: true, level: "read" },
];

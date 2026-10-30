import { activityHandlers } from "./activity.handlers";
import { authHandlers } from "./auth.handlers";
import { commentHandlers } from "./comment.handlers";
import { communityHandlers } from "./community.handlers";
import { customRoleHandlers } from "./customRole.handlers";
import { dmHandlers } from "./dm.handlers";
import { fileHandlers } from "./file.handlers";
import { initiativeHandlers } from "./initiative.handlers";
import { notificationHandlers } from "./notification.handlers";
import { projectHandlers } from "./project.handlers";
import { propertyHandlers } from "./property.handlers";
import { shareHandlers } from "./share.handlers";
import { tagHandlers } from "./tag.handlers";
import { taskHandlers } from "./task.handlers";
import { toolCountHandlers } from "./toolCount.handlers";
import { toolLayoutHandlers } from "./toolLayout.handlers";
import { userHandlers } from "./user.handlers";
import { versionHandlers } from "./version.handlers";

export const handlers = [
  ...authHandlers,
  ...communityHandlers,
  ...customRoleHandlers,
  ...initiativeHandlers,
  ...projectHandlers,
  ...toolLayoutHandlers,
  ...taskHandlers,
  ...tagHandlers,
  ...fileHandlers,
  ...activityHandlers,
  ...commentHandlers,
  ...userHandlers,
  ...propertyHandlers,
  ...dmHandlers,
  ...toolCountHandlers,
  ...notificationHandlers,
  ...shareHandlers,
  ...versionHandlers,
];

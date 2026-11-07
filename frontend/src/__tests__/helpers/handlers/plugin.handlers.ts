import { HttpResponse } from "msw";

import { communityHttp } from "../communityHttp";

/**
 * The community's installed plug-ins, as the widget catalog lists them.
 *
 * A widget's config dialog reads it whenever it is open, for the statements
 * that may read a plug-in as well as for a plug-in's own widgets. None are
 * installed unless a suite says so.
 */
export const pluginHandlers = [
  communityHttp.get("/plugins/widget-catalog", () => HttpResponse.json({ items: [] })),
];

/**
 * Every way rendering a widget can fail, in one place.
 *
 * Three layers can reject a widget — the runtime that executes it, the
 * validator that checks what it drew, and the tile that couldn't find a module
 * for it — and the viewer sees one error tile regardless. Collecting the codes
 * here gives that tile a single union to localize, and gives
 * `widgetErrors.test.ts` something to check the locale files against, so a new
 * failure mode cannot ship without a message in every language.
 */

import { SandboxErrorCode } from "./runtime/sandbox";
import { SceneErrorCode } from "./validateScene";

export const WidgetErrorCode = {
  ...SandboxErrorCode,
  ...SceneErrorCode,
  /** The definition names a widget type this build has no module for — an
   *  install from a listing built against a newer app. */
  TYPE_UNSUPPORTED: "WIDGET_TYPE_UNSUPPORTED",
  /** The plug-in behind this widget did not answer, or answered with something the
   *  proxy will not pass on. One tile says so; the rest of the canvas is
   *  unaffected, and the last good rows keep showing for their stale window. */
  PLUGIN_UNAVAILABLE: "WIDGET_PLUGIN_UNAVAILABLE",
  /** The catalog answered and the plug-in this widget draws from is not in it —
   *  uninstalled, or switched off. The definition is kept as-is; the tile asks
   *  for the plug-in to be reconnected rather than posing as an access outcome. */
  PLUGIN_NOT_INSTALLED: "WIDGET_PLUGIN_NOT_INSTALLED",
  /** This widget's own fetch failed — the network, or the server. Deliberately
   *  distinct from the tile's "you can't see this" state: a request that never
   *  completed says nothing about what the viewer is allowed to see, and
   *  reporting it as an access outcome would be a claim we have not
   *  established. */
  DATA_UNAVAILABLE: "WIDGET_DATA_UNAVAILABLE",
} as const;

export type WidgetErrorCode = (typeof WidgetErrorCode)[keyof typeof WidgetErrorCode];

// Electron, through a module of the plugins' own, so a test can stand in for
// it without Electron installed.
export {
  app,
  BrowserWindow,
  Menu,
  Notification,
  nativeImage,
  nativeTheme,
  net,
  session,
  Tray,
  WebContentsView,
} from "electron";

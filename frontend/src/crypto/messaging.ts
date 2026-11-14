/**
 * Direct messages, from the client's side.
 *
 * This is the orchestration the page uses: make sure this browser has a device,
 * open sessions with the other party's devices, encrypt once per destination,
 * and collect what has arrived. It is deliberately not React — the ratchet has
 * to advance in a defined order, and a hook re-running is not that.
 *
 * The client is the archive. A collected message is deleted from the server, so
 * what is written to the local log is the only copy this device will have.
 */

export { collect } from "./collect";
export {
  ensureDevice,
  forgetMessagesOnThisDevice,
  registeredDevice,
} from "./device";
export {
  answerNewDevice,
  HISTORY_ASK_NOTICE_MS,
  historyAskWaiting,
} from "./historySync";
export { markRead, unreadIn } from "./readState";
export {
  RecipientHasNoDeviceError,
  sendEdit,
  sendReaction,
  sendRemove,
  sendText,
} from "./send";
export {
  historyAsk,
  messageLog,
  type PeerKeyChange,
  peerDeviceChanges,
  type StoredMessage,
  serveAccount,
} from "./store";
export { wantThreadHistory } from "./threadHistory";
export { ownDeviceWaiting } from "./trust";
export {
  cancelVerification,
  collectVerification,
  confirmMatch,
  DeviceGoneError,
  dismissVerification,
  rejectMatch,
  startVerification,
  subscribeVerification,
  verificationView,
} from "./verification";

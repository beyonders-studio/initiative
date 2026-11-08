// Every app that runs on a device has this content policy: the desktop wrapper
// sends it as a header and the phone build writes it into index.html. The app
// reaches the server the person chose, over https or plain http on a home
// network; scripts load from the bundle. It holds only directives a policy in a
// meta element applies.
export const contentPolicy = [
  "default-src 'self'",
  "script-src 'self' 'wasm-unsafe-eval' https://hcaptcha.com https://*.hcaptcha.com https://challenges.cloudflare.com https://www.google.com https://www.gstatic.com",
  "style-src 'self' 'unsafe-inline' https: http:",
  "font-src 'self' data: https: http:",
  "img-src 'self' data: blob: https: http:",
  "media-src 'self' blob: https: http:",
  "connect-src 'self' data: blob: https: http: wss: ws:",
  "frame-src 'self' https: http:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

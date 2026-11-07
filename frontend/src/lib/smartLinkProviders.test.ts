import { describe, expect, it } from "vitest";

import { matchSmartLinkProvider } from "./smartLinkProviders";

describe("matchSmartLinkProvider", () => {
  it.each([
    [
      "https://x.com/jack/status/20",
      "https://platform.twitter.com/embed/Tweet.html?id=20&dnt=true",
    ],
    [
      "https://twitter.com/jack/status/20?s=46",
      "https://platform.twitter.com/embed/Tweet.html?id=20&dnt=true",
    ],
    [
      "https://x.com/i/web/status/20",
      "https://platform.twitter.com/embed/Tweet.html?id=20&dnt=true",
    ],
    [
      "https://www.reddit.com/r/reddit/comments/87/the_downing_street_memo/",
      "https://embed.reddit.com/r/reddit/comments/87/the_downing_street_memo/",
    ],
    [
      "https://old.reddit.com/r/reddit/comments/87",
      "https://embed.reddit.com/r/reddit/comments/87/",
    ],
  ])("frames %s from the post's own site", (url, embedSrc) => {
    const match = matchSmartLinkProvider(url);
    expect(match.embedSrc).toBe(embedSrc);
  });

  it("gives the id an editor embed stores", () => {
    expect(matchSmartLinkProvider("https://x.com/jack/status/20").ref).toBe("20");
    expect(matchSmartLinkProvider("https://youtu.be/jNQXAC9IVRw").ref).toBe("jNQXAC9IVRw");
    expect(matchSmartLinkProvider("https://www.youtube.com/playlist?list=PL1").ref).toBeUndefined();
  });

  it.each([
    "https://www.youtube.com/watch?v=too-short",
    "https://x.com/home",
    "https://x.com/jack/status/not-a-number",
    "https://www.reddit.com/r/reddit/",
  ])("keeps %s a plain link", (url) => {
    expect(matchSmartLinkProvider(url)).toMatchObject({ id: "generic", embedSrc: null });
  });

  it("reads the height each site's frame reports, and nothing else", () => {
    const x = matchSmartLinkProvider("https://x.com/jack/status/20").heightOf;
    const reddit = matchSmartLinkProvider("https://www.reddit.com/r/reddit/comments/87/").heightOf;
    const resize = {
      "twttr.embed": {
        jsonrpc: "2.0",
        method: "twttr.private.resize",
        params: [{ width: 550, height: 225 }],
      },
    };

    expect(x?.(resize)).toBe(225);
    expect(x?.({ "twttr.embed": { method: "twttr.private.rendered", params: [{}] } })).toBeNull();
    expect(x?.("not a call")).toBeNull();
    expect(reddit?.(JSON.stringify({ type: "resize.embed", data: 412 }))).toBe(412);
    expect(reddit?.(JSON.stringify({ type: "other", data: 412 }))).toBeNull();
    expect(reddit?.("{not json")).toBeNull();
  });
});

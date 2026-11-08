/**
 * The question a notice asks.
 *
 * What is load-bearing here is how much of the answer each reader is shown,
 * because the poll decides it and the card cannot: results withheld until this
 * reader has answered, names withheld permanently on an anonymous poll, and a
 * closed poll that is a result rather than a question. The fourth case is the
 * ballot itself — clicking a choice has to move the row it was clicked on,
 * without waiting for a round trip.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { buildPoll, buildPollOption, buildPost } from "@/__tests__/factories";
import { renderPage } from "@/__tests__/helpers/render";

import { PostPoll } from "./PostPoll";

const vote = vi.fn();
const retract = vi.fn();

vi.mock("@/hooks/usePosts", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("@/hooks/usePosts");
  return {
    ...actual,
    useVoteOnPostPoll: () => ({ mutate: vote, isPending: false }),
    useRetractPostPollVote: () => ({ mutate: retract, isPending: false }),
    usePostPollVoters: () => ({ data: undefined, isLoading: true, isError: false }),
  };
});

const pollPage = (props: Parameters<typeof PostPoll>[0]) => () => <PostPoll {...props} />;

const postWithPoll = (overrides: Parameters<typeof buildPoll>[0] = {}) =>
  buildPost({ poll: buildPoll(overrides) });

describe("PostPoll", () => {
  it("shows the question and its choices", async () => {
    renderPage(pollPage({ post: postWithPoll() }));

    expect(await screen.findByText("Which night works?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Tuesday/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Thursday/ })).toBeInTheDocument();
  });

  it("sends the ballot for the choice that was clicked", async () => {
    vote.mockClear();
    const post = postWithPoll();
    renderPage(pollPage({ post }));

    await userEvent.click(await screen.findByRole("button", { name: /Tuesday/ }));

    await waitFor(() =>
      expect(vote).toHaveBeenCalledWith({ option_ids: [post.poll?.options[0].id] })
    );
  });

  it("adds to the ballot rather than replacing it when several may be picked", async () => {
    vote.mockClear();
    const options = [
      buildPollOption("Tuesday", { voted_by_me: true, vote_count: 1 }),
      buildPollOption("Thursday"),
    ];
    const post = postWithPoll({ allows_multiple: true, options, has_voted: true });
    renderPage(pollPage({ post }));

    await userEvent.click(await screen.findByRole("button", { name: /Thursday/ }));

    await waitFor(() =>
      expect(vote).toHaveBeenCalledWith({ option_ids: [options[0].id, options[1].id] })
    );
  });

  it("clears the answer when the only chosen option is clicked again", async () => {
    retract.mockClear();
    const options = [
      buildPollOption("Tuesday", { voted_by_me: true, vote_count: 1 }),
      buildPollOption("Thursday"),
    ];
    renderPage(pollPage({ post: postWithPoll({ options, has_voted: true, total_voters: 1 }) }));

    await userEvent.click(await screen.findByRole("button", { name: /Tuesday/ }));

    await waitFor(() => expect(retract).toHaveBeenCalled());
  });

  it("shows no counts while the results are withheld", async () => {
    const options = [
      buildPollOption("Tuesday", { vote_count: null }),
      buildPollOption("Thursday", { vote_count: null }),
    ];
    renderPage(
      pollPage({
        post: postWithPoll({
          hide_results: true,
          results_visible: false,
          total_voters: null,
          options,
        }),
      })
    );

    expect(await screen.findByText(/results appear once you answer/i)).toBeInTheDocument();
    expect(screen.queryByText(/answered/i)).not.toBeInTheDocument();
    // And no roster either: counting the names would read the results out.
    expect(screen.queryByRole("button", { name: /who voted/i })).not.toBeInTheDocument();
  });

  it("offers no roster on an anonymous poll, but still shows the totals", async () => {
    renderPage(
      pollPage({ post: postWithPoll({ is_anonymous: true, total_voters: 3, has_voted: true }) })
    );

    expect(await screen.findByText(/3 people answered/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /who voted/i })).not.toBeInTheDocument();
  });

  it("offers the roster on a named poll somebody has answered", async () => {
    renderPage(pollPage({ post: postWithPoll({ total_voters: 2 }) }));

    expect(await screen.findByRole("button", { name: /who voted/i })).toBeInTheDocument();
  });

  it("takes no more answers once the poll has closed", async () => {
    vote.mockClear();
    renderPage(
      pollPage({
        post: postWithPoll({ is_closed: true, closes_at: "2026-01-01T00:00:00.000Z" }),
      })
    );

    const choice = await screen.findByRole("button", { name: /Tuesday/ });
    expect(choice).toBeDisabled();
    expect(screen.getByText(/closed/i)).toBeInTheDocument();
    await userEvent.click(choice);
    expect(vote).not.toHaveBeenCalled();
  });

  it("takes no answers on a notice that has not gone up yet", async () => {
    vote.mockClear();
    const post = buildPost({
      poll: buildPoll(),
      is_published: false,
      published_at: null,
      scheduled_for: "2099-01-01T00:00:00.000Z",
    });
    renderPage(pollPage({ post }));

    expect(await screen.findByRole("button", { name: /Tuesday/ })).toBeDisabled();
  });
});

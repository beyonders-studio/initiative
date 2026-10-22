/**
 * Where a sign-in goes. A browser, and a page a link opened for one server,
 * show the kind of server as a chip; signing in or up in the app picks one
 * inside the card and keeps the address it was given.
 */
import { Capacitor } from "@capacitor/core";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";

import { buildUser } from "@/__tests__/factories";
import { server } from "@/__tests__/helpers/msw-server";
import { renderWithProviders } from "@/__tests__/helpers/render";
import {
  CLOUD_ORIGIN,
  CLOUD_SERVER_URL,
  getSelfHostedAddress,
  setSelfHostedAddress,
} from "@/lib/serverStorage";
import { freshAnswers, readStartDraft, saveStartDraft } from "@/lib/startFlow";

import { ServerChip, ServerPicker, ServerSubtitle } from "./ServerChoice";

const asDemo = http.get("/api/v1/auth/bootstrap", () =>
  HttpResponse.json({ has_users: true, public_registration_enabled: false, demo: true })
);

const mocks = vi.hoisted(() => ({
  clearStart: vi.fn(),
  appEnvironment: vi.fn(async () => ({}) as { cleartextPermitted?: boolean }),
}));

vi.mock("@/plugins/appEnvironment", () => ({ default: { get: () => mocks.appEnvironment() } }));

vi.mock("@/lib/startFlow", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/startFlow")>();
  mocks.clearStart.mockImplementation(actual.clearStart);
  return { ...actual, clearStart: () => mocks.clearStart() };
});

describe("ServerChip", () => {
  it("shows the kind of server without letting it change", () => {
    renderWithProviders(<ServerChip />);

    expect(screen.getByText(/^self-hosted$/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says Demo on the demo deployment", async () => {
    server.use(asDemo);
    renderWithProviders(<ServerChip />);

    expect(await screen.findByText("Demo")).toBeInTheDocument();
    expect(screen.queryByText(/^self-hosted$/i)).not.toBeInTheDocument();
  });

  it("says Initiative Cloud on Initiative Cloud", () => {
    renderWithProviders(<ServerChip />, { server: { getServerOrigin: () => CLOUD_ORIGIN } });

    expect(screen.getByLabelText("Server: Initiative Cloud")).toBeInTheDocument();
  });
});

describe("ServerSubtitle", () => {
  it("shows a browser only the chip, since it is on its server already", () => {
    renderWithProviders(<ServerSubtitle />, { server: { isNativePlatform: false } });

    expect(screen.getByText(/^self-hosted$/i)).toBeInTheDocument();
    expect(screen.queryByText(/^sign in to/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^server$/i })).not.toBeInTheDocument();
  });

  it("opens the address from the app's server menu", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ServerSubtitle />, {
      server: {
        isNativePlatform: true,
        serverUrl: "http://10.0.2.2:8000/api/v1",
        getServerOrigin: () => "http://10.0.2.2:8000",
      },
    });

    const menu = screen.getByRole("button", { name: /^server$/i });
    expect(menu).toHaveTextContent("10.0.2.2:8000");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

    await user.click(menu);
    expect(screen.getByRole("menuitem", { name: /initiative cloud/i })).not.toHaveAttribute(
      "aria-disabled"
    );
    await user.click(screen.getByRole("menuitem", { name: /your own server/i }));

    expect(screen.getByRole("textbox", { name: /server address/i })).toBeInTheDocument();
  });

  it("signs the app in to Initiative Cloud, with your own server a choice away", async () => {
    const user = userEvent.setup();
    const setServerUrl = vi.fn();
    renderWithProviders(<ServerSubtitle />, {
      server: {
        isNativePlatform: true,
        serverUrl: CLOUD_SERVER_URL,
        getServerOrigin: () => CLOUD_ORIGIN,
        setServerUrl,
      },
    });

    const menu = screen.getByRole("button", { name: /^server$/i });
    expect(menu).toHaveTextContent("initiativetasks.com");
    expect(screen.getByLabelText("Server: Initiative Cloud")).toBeInTheDocument();

    await user.click(menu);
    await user.click(screen.getByRole("menuitem", { name: /initiative cloud/i }));
    expect(setServerUrl).not.toHaveBeenCalled();

    await user.click(menu);
    await user.click(screen.getByRole("menuitem", { name: /your own server/i }));
    expect(screen.getByRole("textbox", { name: /server address/i })).toHaveValue("");
  });

  it("moves the app from its own server to Initiative Cloud, signed out of the last", async () => {
    const user = userEvent.setup();
    saveStartDraft(freshAnswers("personal"));
    const logout = vi.fn();
    const setServerUrl = vi.fn();
    renderWithProviders(<ServerSubtitle />, {
      auth: { user: buildUser(), logout },
      server: {
        isNativePlatform: true,
        serverUrl: "https://old.example.com/api/v1",
        getServerOrigin: () => "https://old.example.com",
        setServerUrl,
      },
    });

    await user.click(screen.getByRole("button", { name: /^server$/i }));
    await user.click(screen.getByRole("menuitem", { name: /initiative cloud/i }));

    await waitFor(() => expect(setServerUrl).toHaveBeenCalledWith(CLOUD_SERVER_URL));
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(
      setServerUrl.mock.invocationCallOrder[0]
    );
    expect(readStartDraft()).toBeNull();
  });

  it("signs the app in to Demo on the demo deployment, menu and all", async () => {
    server.use(asDemo);
    const user = userEvent.setup();
    renderWithProviders(<ServerSubtitle />, {
      server: { isNativePlatform: true, getServerOrigin: () => "https://demo.example" },
    });

    const menu = screen.getByRole("button", { name: /^server$/i });
    await waitFor(() => expect(menu).toHaveTextContent("Demo"));
    expect(screen.getByLabelText("Server: Demo")).toBeInTheDocument();
    await user.click(menu);
    expect(screen.getByRole("menuitem", { name: /your own server/i })).toBeInTheDocument();
  });
});

describe("ServerPicker", () => {
  it("starts the app on Initiative Cloud, asking for no address", () => {
    renderWithProviders(<ServerPicker />, {
      server: {
        isNativePlatform: true,
        serverUrl: CLOUD_SERVER_URL,
        getServerOrigin: () => CLOUD_ORIGIN,
      },
    });

    expect(screen.getByRole("combobox", { name: /^server$/i })).toHaveTextContent(
      "Initiative Cloud"
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("shows a browser the chip, since it is on its server already", () => {
    renderWithProviders(<ServerPicker />, { server: { isNativePlatform: false } });

    expect(screen.getByText(/^self-hosted$/i)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("moves the app to another self-hosted server, signed out of the last", async () => {
    const user = userEvent.setup();
    setSelfHostedAddress("https://old.example.com");
    saveStartDraft(freshAnswers("personal"));
    const logout = vi.fn();
    const setServerUrl = vi.fn();
    const testServerConnection = vi.fn().mockResolvedValue({ valid: true });
    renderWithProviders(<ServerPicker />, {
      auth: { user: buildUser(), logout },
      server: {
        isNativePlatform: true,
        serverUrl: "https://old.example.com/api/v1",
        setServerUrl,
        testServerConnection,
      },
    });

    const address = screen.getByRole("textbox", { name: /server address/i });
    expect(address).toHaveValue("https://old.example.com");
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(testServerConnection).toHaveBeenCalledWith("https://new.example.com");
    expect(setServerUrl).toHaveBeenCalledWith("https://new.example.com");
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(
      setServerUrl.mock.invocationCallOrder[0]
    );
    expect(readStartDraft()).toBeNull();
    expect(getSelfHostedAddress()).toBe("https://new.example.com");
  });

  it.each([
    ["an Android release build", "android", false, /https servers only/i],
    ["an Android debug build", "android", true, /could not connect to server/i],
    ["an iPhone", "ios", undefined, /https servers only/i],
    ["the desktop app", "electron", undefined, /could not connect to server/i],
  ])(
    "on %s, says why a plain-HTTP address did not connect",
    async (_, platform, cleartext, message) => {
      const user = userEvent.setup();
      vi.spyOn(Capacitor, "getPlatform").mockReturnValue(platform as string);
      mocks.appEnvironment.mockResolvedValue({
        cleartextPermitted: cleartext as boolean | undefined,
      });
      renderWithProviders(<ServerPicker />, {
        server: {
          isNativePlatform: true,
          serverUrl: "https://home.example.com/api/v1",
          testServerConnection: vi.fn().mockResolvedValue({ valid: false }),
        },
      });

      const address = screen.getByRole("textbox", { name: /server address/i });
      await user.clear(address);
      await user.type(address, "http://192.168.1.20:8000");
      await user.click(screen.getByRole("button", { name: /^connect$/i }));

      expect(await screen.findByText(message)).toBeInTheDocument();
    }
  );

  it("holds the server choice while an address is being reached", async () => {
    const user = userEvent.setup();
    let answer: (result: { valid: boolean }) => void = () => {};
    const testServerConnection = vi.fn(
      () => new Promise<{ valid: boolean }>((resolve) => (answer = resolve))
    );
    renderWithProviders(<ServerPicker />, {
      server: {
        isNativePlatform: true,
        serverUrl: "https://home.example.com/api/v1",
        testServerConnection,
      },
    });

    const choice = screen.getByRole("combobox", { name: /^server$/i });
    const address = screen.getByRole("textbox", { name: /server address/i });
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(choice).toBeDisabled();
    answer({ valid: false });
    await waitFor(() => expect(choice).toBeEnabled());
  });

  it("says the app is connected to the address it shows", () => {
    setSelfHostedAddress("https://home.example.com");
    renderWithProviders(<ServerPicker />, {
      server: { isNativePlatform: true, serverUrl: "https://home.example.com/api/v1" },
    });

    expect(screen.getByRole("button", { name: /^connected$/i })).toBeDisabled();
  });

  it("stays on the server, signed in, when the switch cannot finish", async () => {
    const user = userEvent.setup();
    mocks.clearStart.mockRejectedValueOnce(new Error("storage unavailable"));
    const logout = vi.fn();
    const setServerUrl = vi.fn();
    renderWithProviders(<ServerPicker />, {
      auth: { user: buildUser(), logout },
      server: {
        isNativePlatform: true,
        serverUrl: "https://old.example.com/api/v1",
        setServerUrl,
        testServerConnection: vi.fn().mockResolvedValue({ valid: true }),
      },
    });

    const address = screen.getByRole("textbox", { name: /server address/i });
    await user.clear(address);
    await user.type(address, "https://new.example.com");
    await user.click(screen.getByRole("button", { name: /^connect$/i }));

    expect(await screen.findByText(/could not connect to server/i)).toBeInTheDocument();
    expect(logout).not.toHaveBeenCalled();
    expect(setServerUrl).not.toHaveBeenCalled();
  });
});

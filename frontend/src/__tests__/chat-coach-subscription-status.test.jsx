import React from "react";
import "@testing-library/jest-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import axios from "axios";

import ChatCoach from "@/components/ChatCoach";

jest.mock("axios");
jest.mock("@/context/LanguageContext", () => ({
  useLanguage: () => ({
    lang: "en",
    t: (key) => (key === "chat.unlimited" ? "Unlimited access" : key),
  }),
}));
jest.mock("react-router-dom", () => ({
  ...jest.requireActual("react-router-dom"),
  useNavigate: () => jest.fn(),
}));

const freeStatus = (messages_remaining) => ({
  tier: "free",
  tier_name: "Free",
  is_premium: false,
  is_unlimited: false,
  messages_limit: 10,
  messages_remaining,
});

const unlimitedStatus = (tier) => ({
  tier,
  tier_name: tier === "trial" ? "Trial" : "Premium",
  is_premium: true,
  is_unlimited: true,
  messages_limit: null,
  messages_remaining: null,
  messages_used: 4,
});

function renderChat(isOpen = true) {
  return render(<ChatCoach isOpen={isOpen} onClose={jest.fn()} />);
}

describe("ChatCoach subscription status", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    axios.get.mockImplementation((url) => (
      String(url).includes("/subscription/status")
        ? Promise.resolve({ data: freeStatus(3) })
        : Promise.resolve({ data: [] })
    ));
  });

  test("FREE users may send with remaining quota and are blocked at zero", async () => {
    const view = renderChat();
    expect(await screen.findByTestId("chat-input")).toBeInTheDocument();
    view.unmount();

    axios.get.mockImplementation((url) => (
      String(url).includes("/subscription/status")
        ? Promise.resolve({ data: freeStatus(0) })
        : Promise.resolve({ data: [] })
    ));
    renderChat();
    expect(await screen.findByText(/atteint ta limite/i)).toBeInTheDocument();
    expect(screen.queryByTestId("chat-input")).not.toBeInTheDocument();
  });

  test.each(["trial", "premium"])(
    "%s users have unlimited access without a fabricated counter",
    async (tier) => {
      axios.get.mockImplementation((url) => (
        String(url).includes("/subscription/status")
          ? Promise.resolve({ data: unlimitedStatus(tier) })
          : Promise.resolve({ data: [] })
      ));
      axios.post.mockResolvedValue({
        data: { message_id: "assistant-1", response: "Reply", messages_remaining: 999 },
      });
      renderChat();

      expect(await screen.findByText("Unlimited access")).toBeInTheDocument();
      expect(screen.getByTestId("chat-input")).toBeInTheDocument();
      expect(screen.queryByText(/999|messages$/i)).not.toBeInTheDocument();

      fireEvent.change(screen.getByTestId("chat-input"), { target: { value: "Hello" } });
      fireEvent.click(screen.getByTestId("send-btn"));
      await screen.findByText("Reply");

      expect(screen.getByText("Unlimited access")).toBeInTheDocument();
      expect(screen.queryByText(/999|messages$/i)).not.toBeInTheDocument();
    }
  );

  test("HTTP 429 is shown to the user and does not make unlimited quota assumptions", async () => {
    axios.get.mockImplementation((url) => (
      String(url).includes("/subscription/status")
        ? Promise.resolve({ data: unlimitedStatus("trial") })
        : Promise.resolve({ data: [] })
    ));
    axios.post.mockRejectedValue({
      response: { status: 429, data: { detail: "Technical anti-abuse limit reached." } },
    });
    renderChat();

    fireEvent.change(await screen.findByTestId("chat-input"), { target: { value: "Hello" } });
    fireEvent.click(screen.getByTestId("send-btn"));

    expect(await screen.findByText(/Technical anti-abuse limit reached/i)).toBeInTheDocument();
    expect(screen.getByText("Unlimited access")).toBeInTheDocument();
  });

  test("reopening the Coach refreshes FREE access to the current TRIAL status", async () => {
    const statuses = [freeStatus(0), unlimitedStatus("trial")];
    axios.get.mockImplementation((url) => (
      String(url).includes("/subscription/status")
        ? Promise.resolve({ data: statuses.shift() })
        : Promise.resolve({ data: [] })
    ));
    const view = renderChat();
    expect(await screen.findByText(/atteint ta limite/i)).toBeInTheDocument();

    view.rerender(<ChatCoach isOpen={false} onClose={jest.fn()} />);
    view.rerender(<ChatCoach isOpen onClose={jest.fn()} />);

    await waitFor(() => expect(screen.getByText("Unlimited access")).toBeInTheDocument());
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });
});

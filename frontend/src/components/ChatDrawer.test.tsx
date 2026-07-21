import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { RuntimeState } from "../types";
import { ChatDrawer } from "./ChatDrawer";

vi.mock("../api", () => ({
  api: {
    sendChat: vi.fn(),
    chatHistory: vi.fn(),
    usage: vi.fn(),
    decidePreferenceChange: vi.fn()
  }
}));

const runtime: RuntimeState = {
  providers: [],
  mode: "degraded",
  selection: { provider: "codex", model: "gpt-5.6-terra", reasoning_effort: "low" }
};

describe("ChatDrawer preference confirmation", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    vi.mocked(api.usage).mockResolvedValue({
      totals: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, runs: 0 },
      by_agent: []
    });
    vi.mocked(api.sendChat).mockResolvedValue({
      conversation_id: "conversation-1",
      message_id: "message-1",
      content: "This would broaden your saved search. Review and confirm before I apply it.",
      provider: "carivyo",
      model: "deterministic-router",
      usage: {
        input_tokens: 8,
        output_tokens: 12,
        cache_read_tokens: 0,
        kind: "estimated",
        context: []
      },
      intent: "confirm_preference_update",
      search_requested: false,
      preference_confirmation: {
        id: "change-1",
        summary: "preferred locations → Singapore"
      }
    });
    vi.mocked(api.decidePreferenceChange).mockResolvedValue({
      id: "change-1",
      status: "applied",
      summary: "preferred locations → Singapore",
      search_requested: true,
      search_run_id: "run-1"
    });
  });

  it("does not broaden until the user explicitly applies the typed change", async () => {
    const onSearchStarted = vi.fn();
    render(
      <ChatDrawer
        open
        onClose={vi.fn()}
        currentPage="jobs"
        runtime={runtime}
        onOpenAISettings={vi.fn()}
        onSearchStarted={onSearchStarted}
      />
    );

    fireEvent.change(screen.getByPlaceholderText(/ask, explain/i), {
      target: { value: "Show Backend Engineer roles in Singapore" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByRole("button", { name: "Apply change" })).toBeInTheDocument();
    expect(api.sendChat).toHaveBeenCalledWith(
      expect.objectContaining({ use_ai: false })
    );
    expect(api.decidePreferenceChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Apply change" }));

    await waitFor(() => expect(api.decidePreferenceChange).toHaveBeenCalledWith("change-1", true));
    expect(await screen.findByText(/preference applied/i)).toBeInTheDocument();
    expect(onSearchStarted).toHaveBeenCalledWith("run-1");
  });
});

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function BrokenView(): never {
  throw new Error("sensitive implementation detail");
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
  });

  it("shows a safe recovery state without exposing internal errors", () => {
    render(
      <ErrorBoundary>
        <BrokenView />
      </ErrorBoundary>
    );

    expect(screen.getByRole("heading", { name: /could not finish rendering/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reload workspace/i })).toBeInTheDocument();
    expect(screen.queryByText(/sensitive implementation detail/i)).not.toBeInTheDocument();
  });
});

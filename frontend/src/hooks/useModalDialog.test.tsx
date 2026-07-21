import { useRef, useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useModalDialog } from "./useModalDialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useModalDialog(open, dialogRef, closeRef, () => setOpen(false));

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open dialog
      </button>
      {open ? (
        <section ref={dialogRef} role="dialog" aria-label="Test dialog" tabIndex={-1}>
          <button ref={closeRef} type="button" onClick={() => setOpen(false)}>
            Close dialog
          </button>
          <button type="button">Last action</button>
        </section>
      ) : null}
    </>
  );
}

describe("useModalDialog", () => {
  it("traps focus, closes on Escape, and restores the trigger", async () => {
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    trigger.focus();
    fireEvent.click(trigger);
    const close = await screen.findByRole("button", { name: "Close dialog" });
    await waitFor(() => expect(close).toHaveFocus());

    const last = screen.getByRole("button", { name: "Last action" });
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Test dialog" })).toBeNull()
    );
    expect(trigger).toHaveFocus();
  });
});

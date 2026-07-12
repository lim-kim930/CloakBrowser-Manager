import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { CloseModal } from "./CloseModal";

describe("CloseModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<CloseModal open={false} onChoice={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("reports exit with remember flag", () => {
    const onChoice = vi.fn();
    render(<CloseModal open onChoice={onChoice} />);
    fireEvent.click(screen.getByLabelText(/remember/i));
    fireEvent.click(screen.getByRole("button", { name: /quit/i }));
    expect(onChoice).toHaveBeenCalledWith("exit", true);
  });

  it("reports tray without remember by default", () => {
    const onChoice = vi.fn();
    render(<CloseModal open onChoice={onChoice} />);
    fireEvent.click(screen.getByRole("button", { name: /tray/i }));
    expect(onChoice).toHaveBeenCalledWith("tray", false);
  });
});

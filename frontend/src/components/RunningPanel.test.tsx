import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { RunningPanel } from "./RunningPanel";

beforeEach(() => {
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("RunningPanel", () => {
  it("shows the desktop-window hint", () => {
    render(<RunningPanel profileId="p1" cdpUrl="/api/profiles/p1/cdp" />);
    expect(screen.getByText(/desktop/i)).toBeInTheDocument();
  });

  it("copies the absolute CDP url", async () => {
    render(<RunningPanel profileId="p1" cdpUrl="/api/profiles/p1/cdp" />);
    fireEvent.click(screen.getByRole("button", { name: /copy cdp/i }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      expect.stringContaining("/api/profiles/p1/cdp"),
    );
  });

  it("omits the CDP row when cdpUrl is null", () => {
    render(<RunningPanel profileId="p1" cdpUrl={null} />);
    expect(screen.queryByRole("button", { name: /copy cdp/i })).toBeNull();
  });
});

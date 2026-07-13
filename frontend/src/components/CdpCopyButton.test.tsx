import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { CdpCopyButton } from "./CdpCopyButton";
import { setApiBase } from "../lib/api";

const writeText = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
  writeText.mockClear();
});

describe("CdpCopyButton", () => {
  it("copies the absolute CDP URL and confirms", async () => {
    setApiBase("http://127.0.0.1:8123");
    render(<CdpCopyButton cdpUrl="/api/profiles/abc/cdp" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("http://127.0.0.1:8123/api/profiles/abc/cdp"),
    );
    expect(screen.getByText("Copied")).toBeDefined();
    setApiBase("");
  });
});

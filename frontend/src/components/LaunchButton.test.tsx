import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { LaunchButton } from "./LaunchButton";

describe("LaunchButton", () => {
  it("disables launch when canLaunch is false", () => {
    const onLaunch = vi.fn();
    render(
      <LaunchButton status="stopped" canLaunch={false} onLaunch={onLaunch} onStop={vi.fn()} />,
    );
    const btn = screen.getByRole("button", { name: /launch/i });
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(onLaunch).not.toHaveBeenCalled();
  });

  it("allows launch by default", () => {
    render(<LaunchButton status="stopped" onLaunch={vi.fn()} onStop={vi.fn()} />);
    expect(screen.getByRole("button", { name: /launch/i })).not.toBeDisabled();
  });
});

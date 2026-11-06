// Independent timer checks. Copy into the reviewed checkout's frontend/tests.
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Dashboard } from "../src/Dashboard";
import type { ApiPort } from "../src/types";

const profile = { targets: [], facts: [], materials: [] };
const empty = { items: [], next_cursor: null, as_of: "2026-11-06T00:00:00Z" };
const show = (api: ApiPort) => render(
  <Dashboard api={api} revision={0} navigate={vi.fn()} headingRef={{ current: null }} />,
);
const settle = () => act(async () => { await Promise.resolve(); });
const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("independent reconnect lifecycle", () => {
  it("automatically retries at 1/2/5/10 seconds and stops after recovery", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    let healthy = false;
    const starts: number[] = [];
    const query = vi.fn(async (path: string) => {
      if (path === "profile") starts.push(Date.now());
      if (!healthy) throw { code: "BUSY", message: "temporary" };
      return path === "profile" ? profile : empty;
    });
    show({ query, command: vi.fn() } as ApiPort);
    await settle();
    expect(starts).toEqual([0]);
    for (const [index, delay] of [1000, 2000, 5000, 10000].entries()) {
      await advance(delay - 1);
      expect(starts).toHaveLength(index + 1);
      if (index === 3) healthy = true;
      await advance(1);
      expect(starts).toHaveLength(index + 2);
    }
    expect(starts).toEqual([0, 1000, 3000, 8000, 18000]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getAllByText("0")).toHaveLength(3);
    await advance(30000);
    expect(starts).toHaveLength(5);
  });

  it("does not automatically retry non-retryable failures but permits explicit recovery", async () => {
    vi.useFakeTimers();
    let healthy = false;
    const query = vi.fn(async (path: string) => {
      if (!healthy) throw { code: "VALIDATION", message: "check settings" };
      return path === "profile" ? profile : empty;
    });
    show({ query, command: vi.fn() } as ApiPort);
    await settle();
    await advance(30000);
    expect(query).toHaveBeenCalledTimes(3);
    healthy = true;
    fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
    await settle();
    expect(query).toHaveBeenCalledTimes(6);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("cancels the pending automatic retry when a manual retry succeeds", async () => {
    vi.useFakeTimers();
    let healthy = false;
    const query = vi.fn(async (path: string) => {
      if (!healthy) throw new Error("network unavailable");
      return path === "profile" ? profile : empty;
    });
    show({ query, command: vi.fn() } as ApiPort);
    await settle();
    healthy = true;
    fireEvent.click(screen.getByRole("button", { name: "重试读取" }));
    await settle();
    expect(query).toHaveBeenCalledTimes(6);
    await advance(30000);
    expect(query).toHaveBeenCalledTimes(6);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not schedule a retry from a rejected request after unmount", async () => {
    vi.useFakeTimers();
    const rejectors: Array<(reason: unknown) => void> = [];
    const query = vi.fn(() => new Promise((_resolve, reject) => rejectors.push(reject)));
    const view = show({ query, command: vi.fn() } as ApiPort);
    view.unmount();
    await act(async () => { rejectors.forEach(reject => reject(new Error("late failure"))); });
    await advance(30000);
    expect(query).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });
});

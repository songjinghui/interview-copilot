// Copy into the reviewed checkout's frontend/tests, run with npm test -- <file>,
// then remove only that review copy. No real service or user data is accessed.
import React from "react";
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../src/App";
import { Dashboard } from "../src/Dashboard";
import type { ApiPort, Profile } from "../src/types";

const empty = { items: [], next_cursor: null, as_of: "2026-11-06T00:00:00Z" };
const profile: Profile = {
  targets: [{ id: "target", revision: 1, label: "已有方向", active: true,
    criteria: { keywords: ["Python"], any_city: true } }],
  facts: [], materials: [],
};
const renderDashboard = (api: ApiPort) => render(
  <Dashboard api={api} revision={0} navigate={vi.fn()} headingRef={{ current: null }} />,
);

describe("independent dashboard review", () => {
  it("does not infer a missing target while records are still loading", () => {
    const api = { query: vi.fn(() => new Promise(() => {})), command: vi.fn() } as ApiPort;
    renderDashboard(api);
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "先整理求职方向" })).toBeNull();
  });

  it("does not infer a missing target after a snapshot failure", async () => {
    const api = { query: vi.fn(async () => { throw new Error("模拟暂时断线"); }),
      command: vi.fn() } as ApiPort;
    renderDashboard(api);
    await screen.findByRole("alert");
    expect(screen.getAllByText("—")).toHaveLength(3);
    expect(screen.queryByRole("heading", { name: "先整理求职方向" })).toBeNull();
  });

  it("recovers a temporary failure on the overview without leaving or reloading the app", async () => {
    let healthy = false;
    const api = { query: vi.fn(async (path: string) => {
      if (!healthy) throw new Error("模拟暂时断线");
      return path === "profile" ? profile : empty;
    }), command: vi.fn() } as ApiPort;
    history.replaceState(null, "", "/?page=dashboard");
    render(<App api={api} />);
    await screen.findByRole("alert");
    healthy = true;
    // A visible retry action or the established reconnect loop may recover.
    const retry = screen.queryByRole("button", { name: /重试|刷新|重新加载/ });
    if (retry) await userEvent.setup().click(retry);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull(), { timeout: 1800 });
    expect(screen.getAllByText("0")).toHaveLength(3);
  });

  it("aggregates all pages and keeps closed statuses out of the active opportunity list", async () => {
    const statuses = ["saved", "deferred", "applying", "applied", "interviewing", "offer", "rejected", "withdrawn", "archived"];
    const api = { query: vi.fn(async (path: string) => {
      if (path === "profile") return profile;
      if (path.startsWith("jobs")) return {
        ...empty, items: Array.from({ length: path.includes("cursor=") ? 1 : 100 }, (_, i) => ({ id: `job-${i}` })),
        next_cursor: path.includes("cursor=") ? null : "next",
      };
      if (path.startsWith("opportunities")) return { ...empty, items: statuses.map((status, i) => ({
        id: `opp-${i}`, title: status, company_name: "测试公司", status,
      })) };
      throw new Error(`Unexpected path: ${path}`);
    }), command: vi.fn() } as ApiPort;
    const { container } = renderDashboard(api);
    await screen.findByText("101");
    expect([...container.querySelectorAll(".metric-card strong")].map(n => n.textContent))
      .toEqual(["101", "2", "2"]);
    expect(container.querySelectorAll(".recent-item")).toHaveLength(4);
    for (const status of ["rejected", "withdrawn", "archived"])
      expect(screen.queryByRole("button", { name: new RegExp(status) })).toBeNull();
  });

  it("moves focus and current navigation on dashboard/profile routes and popstate", async () => {
    const api = { query: vi.fn(async (path: string) => path === "profile" ? profile : empty),
      command: vi.fn() } as ApiPort;
    history.replaceState(null, "", "/");
    render(<App api={api} />);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    const navigation = within(screen.getByRole("navigation", { name: "工作台" }));
    expect(navigation.getByRole("link", { name: "总览" }).getAttribute("aria-current")).toBe("page");
    await userEvent.setup().click(navigation.getByRole("link", { name: "目标与资料" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1, name: "目标与资料" }));
    expect(navigation.getByRole("link", { name: "目标与资料" }).getAttribute("aria-current")).toBe("page");
    history.replaceState(null, "", "/?page=dashboard");
    fireEvent(window, new PopStateEvent("popstate"));
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    expect(navigation.getByRole("link", { name: "总览" }).getAttribute("aria-current")).toBe("page");
  });

  it("keeps normal-sized help text readable against its declared surfaces", () => {
    const css = readFileSync("src/style.css", "utf8");
    const muted = [...css.matchAll(/--muted:\s*(#[0-9a-f]{6})/gi)].at(-1)![1];
    const luminance = (hex: string) => hex.slice(1).match(/../g)!
      .map(channel => parseInt(channel, 16) / 255)
      .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
      .reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
    for (const background of ["#ffffff", "#f5f6f1", "#f9faf7"]) {
      const values = [luminance(muted), luminance(background)].sort((a, b) => b - a);
      const ratio = (values[0] + .05) / (values[1] + .05);
      expect(ratio, `${muted} on ${background}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});

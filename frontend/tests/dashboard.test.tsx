import React from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Dashboard } from "../src/Dashboard";
import type { ApiPort, Opportunity, Page, Profile } from "../src/types";

const profile: Profile = { targets: [], facts: [], materials: [] };
const emptyPage = <T,>(): Page<T> => ({
  items: [],
  next_cursor: null,
  as_of: "2026-11-06T00:00:00Z",
});

describe("overview dashboard", () => {
  it("shows honest empty-state counts and guides a new user to their goal", async () => {
    const api: ApiPort = {
      command: vi.fn(),
      query: vi.fn(async (path: string) => {
        if (path === "profile") return profile;
        if (path.startsWith("jobs")) return emptyPage();
        if (path.startsWith("opportunities")) return emptyPage();
        throw new Error("unexpected query");
      }),
    };
    const navigate = vi.fn();
    render(
      <Dashboard
        api={api}
        revision={0}
        navigate={navigate}
        headingRef={{ current: null }}
      />,
    );

    expect(await screen.findByText("已收录岗位")).toBeTruthy();
    expect(screen.getAllByText("0")).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "先整理求职方向" })).toBeTruthy();
    expect(screen.getByText("这里会显示你已保存的求职机会。")).toBeTruthy();
    expect(screen.queryByText(/08|准备投递/)).toBeNull();
    const continueButton = await screen.findByRole("button", {
      name: "完善求职目标",
    });
    continueButton.click();
    expect(navigate).toHaveBeenCalledWith("profile");
  });

  it("marks every dashboard metric as unavailable when the snapshot request fails", async () => {
    const api: ApiPort = {
      command: vi.fn(),
      query: vi.fn(async () => {
        throw new Error("本地服务暂不可用");
      }),
    };
    render(
      <Dashboard
        api={api}
        revision={0}
        navigate={vi.fn()}
        headingRef={{ current: null }}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "本地服务暂不可用",
    );
    expect(screen.getAllByText("—")).toHaveLength(3);
  });

  it("counts and lists only persisted opportunities using their real statuses", async () => {
    const opportunity = {
      id: "opp-1",
      revision: 1,
      title: "后端工程师",
      company_name: "示例公司",
      note: "",
      status: "interviewing",
      jobs: [],
      preparations: [],
      applications: [],
      cooldown: { status: "unknown", explanation: "待核实" },
    } satisfies Opportunity;
    const api: ApiPort = {
      command: vi.fn(),
      query: vi.fn(async (path: string) => {
        if (path === "profile")
          return {
            ...profile,
            targets: [
              {
                id: "target-1",
                revision: 1,
                label: "后端开发",
                active: true,
                criteria: { keywords: ["Python"], any_city: true },
              },
            ],
          };
        if (path.startsWith("jobs")) return emptyPage();
        if (path.startsWith("opportunities"))
          return { ...emptyPage<Opportunity>(), items: [opportunity] };
        throw new Error("unexpected query");
      }),
    };
    const navigate = vi.fn();
    render(
      <Dashboard
        api={api}
        revision={0}
        navigate={navigate}
        headingRef={{ current: null }}
      />,
    );

    await waitFor(() => expect(screen.getAllByText("1")).toHaveLength(1));
    expect(screen.getByText("后端工程师")).toBeTruthy();
    expect(screen.getByText("面试中")).toBeTruthy();
    screen.getByRole("button", { name: /后端工程师/ }).click();
    expect(navigate).toHaveBeenCalledWith("opportunities", "opp-1");
  });
});

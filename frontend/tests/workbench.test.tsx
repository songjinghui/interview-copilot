import React from "react";
import { existsSync } from "node:fs";
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

async function feature(name: string) {
  expect(
    existsSync(new URL("../src/" + name, import.meta.url)),
    `Required workbench feature missing: ${name}`,
  ).toBe(true);
  return import(/* @vite-ignore */ "../src/" + name);
}

describe("persistent workbench forms", () => {
  it("shows a draft-read error instead of leaving an endless loading indicator", async () => {
    const { ActionForm } = await feature("forms.tsx");
    const { drafts } = await feature("drafts.ts");
    vi.spyOn(drafts, "get").mockRejectedValue(new Error("草稿读取失败"));
    render(
      <ActionForm
        id="read-failure"
        title="编辑"
        fields={[]}
        command="SaveTarget"
        api={{ command: vi.fn() }}
        input={() => ({})}
        onSaved={() => {}}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "草稿读取失败",
    );
  });
  it("does not send commands or claim persistence if IndexedDB writing fails", async () => {
    const { ActionForm } = await feature("forms.tsx");
    const { drafts } = await feature("drafts.ts");
    const broken = vi
      .spyOn(drafts, "put")
      .mockRejectedValue(new Error("草稿存储不可用"));
    const command = vi.fn();
    render(
      <ActionForm
        id="storage-failure"
        title="确认"
        fields={[]}
        command="ConfirmPreparation"
        api={{ command }}
        input={() => ({ preparation_id: "p", step: "materials" })}
        onSaved={() => {}}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "保存" }));
    expect(await screen.findByText("草稿存储不可用")).toBeTruthy();
    expect(command).not.toHaveBeenCalled();
    expect(screen.queryByText(/草稿已保留/)).toBeNull();
    broken.mockRestore();
  });

  it("keeps a material draft on its original parent until the user explicitly rebases", async () => {
    const { ActionForm } = await feature("forms.tsx");
    const command = vi.fn().mockRejectedValue({
      code: "REVISION_CONFLICT",
      message: "Changed",
      details: { parent_version_id: "v2" },
    });
    const props = {
      id: "parent-conflict",
      title: "修订",
      fields: [{ name: "text", label: "修订正文", required: true }],
      command: "SaveMaterialVersion",
      api: { command },
      input: (v: Record<string, string>) => ({
        text: v.text,
        parent_version_id: v._parent_version_id,
      }),
      onSaved: vi.fn(),
    };
    const view = render(
      <ActionForm
        {...props}
        initial={{ text: "draft", _parent_version_id: "v1" }}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "保存" }));
    await screen.findByText(/记录已在其他操作中更新/);
    view.unmount();
    render(
      <ActionForm
        {...props}
        initial={{ text: "remote", _parent_version_id: "v2" }}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "保存" }));
    await waitFor(() => expect(command).toHaveBeenCalledTimes(2));
    expect(command.mock.calls[1][0].input.parent_version_id).toBe("v1");
    await userEvent.click(
      await screen.findByRole("button", {
        name: "我已核对当前记录，保留草稿继续保存",
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(command).toHaveBeenCalledTimes(3));
    expect(command.mock.calls[2][0].input).toEqual({
      text: "draft",
      parent_version_id: "v2",
    });
  });
  it("keeps unsaved input across remount and clears only after successful save", async () => {
    const { ActionForm } = await feature("forms.tsx");
    const command = vi
      .fn()
      .mockRejectedValueOnce({ code: "VALIDATION", message: "请补全资料" })
      .mockResolvedValue({ data: { id: "saved" } });
    const props = {
      id: "draft-test",
      title: "简历",
      fields: [
        { name: "text", label: "简历正文", multiline: true, required: true },
      ],
      command: "ImportMaterial",
      api: { command },
      input: (v: Record<string, string>) => v,
      onSaved: vi.fn(),
    };
    const mounted = render(<ActionForm {...props} />);
    await userEvent.type(await screen.findByLabelText("简历正文"), "我的经历");
    await waitFor(() =>
      expect(screen.getByText("草稿已保存在此浏览器")).toBeTruthy(),
    );
    mounted.unmount();
    render(<ActionForm {...props} />);
    await waitFor(() =>
      expect(
        (screen.getByLabelText("简历正文") as HTMLTextAreaElement).value,
      ).toBe("我的经历"),
    );
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("请补全资料")).toBeTruthy();
    expect(
      (screen.getByLabelText("简历正文") as HTMLTextAreaElement).value,
    ).toBe("我的经历");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
    const { drafts } = await feature("drafts.ts");
    expect(await drafts.get("draft-test")).toBeUndefined();
  });

  it("reuses the persisted envelope after an uncertain network outcome, including reload", async () => {
    const { ActionForm } = await feature("forms.tsx");
    const command = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValue({ data: { id: "saved" } });
    const props = {
      id: "retry-test",
      title: "岗位",
      fields: [{ name: "title", label: "岗位名称", required: true }],
      command: "ImportJob",
      api: { command },
      input: (v: Record<string, string>) => v,
      onSaved: vi.fn(),
    };
    const mount = render(<ActionForm {...props} />);
    await userEvent.type(await screen.findByLabelText("岗位名称"), "开发");
    await userEvent.click(screen.getByRole("button", { name: "保存" }));
    await screen.findByRole("button", { name: "重试保存" });
    const first = command.mock.calls[0][0];
    mount.unmount();
    render(<ActionForm {...props} />);
    await userEvent.click(
      await screen.findByRole("button", { name: "重试保存" }),
    );
    await waitFor(() => expect(command).toHaveBeenCalledTimes(2));
    expect(command.mock.calls[1][0]).toEqual(first);
  });
});

describe("preparation actions", () => {
  it.each(["unknown", "absent", "present"])(
    "uses server next_step for %s and never submits an application",
    async (status) => {
      const { Preparation } = await feature("opportunities.tsx");
      const api = { command: vi.fn().mockResolvedValue({ data: {} }) };
      const prep = {
        id: "prep",
        revision: 1,
        next_step: "materials",
        cooldown_status: status,
        cooldown_snapshot: { status, explanation: "待核实" },
        job: { title: "开发", revision: 1 },
        resume: null,
        resume_exception: "此渠道无需简历",
        channel: "官网",
      };
      const props = { prep, api, refresh: vi.fn() };
      const view = render(<Preparation {...props} />);
      await userEvent.click(
        await screen.findByRole("button", { name: "确认材料" }),
      );
      await waitFor(() => expect(api.command).toHaveBeenCalledTimes(1));
      expect(api.command.mock.calls[0][0].command).toBe("ConfirmPreparation");
      expect(api.command.mock.calls[0][0].input.step).toBe("materials");
      view.rerender(
        <Preparation
          {...props}
          prep={{
            ...prep,
            revision: 2,
            next_step: status === "present" ? "cooldown" : "manual_apply",
          }}
        />,
      );
      if (status === "present") {
        await userEvent.click(
          await screen.findByRole("button", {
            name: "确认了解冷却期，仍自行投递",
          }),
        );
        await waitFor(() => expect(api.command).toHaveBeenCalledTimes(2));
        expect(api.command.mock.calls[1][0].input.step).toBe("cooldown");
      } else {
        expect(screen.queryByText("确认了解冷却期，仍自行投递")).toBeNull();
      }
      expect(
        api.command.mock.calls.every(
          (call) => call[0].command === "ConfirmPreparation",
        ),
      ).toBe(true);
    },
  );

  it("hides external action when unlinked and renders hostile JD text literally", async () => {
    const { Preparation } = await feature("opportunities.tsx");
    render(
      <Preparation
        prep={{
          id: "p",
          revision: 1,
          next_step: "relink_job",
          job: { title: "<script>attack()</script>", revision: 1 },
          resume: null,
          channel: "官网",
          apply_url: "javascript:attack()",
          cooldown_snapshot: { status: "unknown" },
        }}
        api={{ command: vi.fn() }}
        refresh={() => {}}
      />,
    );
    expect(await screen.findByText(/请先重新关联岗位/)).toBeTruthy();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.queryByRole("link", { name: "打开投递页面" })).toBeNull();
    expect(screen.queryByRole("button", { name: "确认材料" })).toBeNull();
  });
});

describe("API session", () => {
  it("removes bootstrap fragment before exchange and stores only session token", async () => {
    const { Api } = await feature("api.ts");
    history.replaceState(null, "", "/#bootstrap=one-use");
    const fetcher = vi.fn(async () => {
      expect(location.hash).toBe("");
      return new Response(JSON.stringify({ token: "session-token" }), {
        status: 200,
      });
    });
    const api = new Api(fetcher);
    await api.connect();
    expect(sessionStorage.getItem("interview-session")).toBe("session-token");
    expect(fetcher.mock.calls).toHaveLength(1);
  });
});

describe("workbench pages", () => {
  it("preserves referenced facts when revising material text", async () => {
    const { ProfilePage } = await feature("profile.tsx");
    const latest = {
      id: "v1",
      material_id: "m1",
      revision: 1,
      text_content: "旧简历",
      fact_snapshot: { facts: [{ id: "f1" }] },
    };
    const api = {
      query: vi.fn(async (path: string) =>
        path === "profile"
          ? {
              targets: [],
              facts: [],
              materials: [{ id: "m1", label: "资料", latest_version: latest }],
            }
          : { items: [latest] },
      ),
      command: vi.fn().mockResolvedValue({ data: {} }),
    };
    render(<ProfilePage api={api} revision={0} refresh={() => {}} />);
    await userEvent.click(await screen.findByText("资料 · 最新 v1"));
    const { within } = await import("@testing-library/react");
    const form = within(screen.getByRole("form", { name: "另存一个修订" }));
    await userEvent.type(await form.findByLabelText("修订正文"), "补充");
    await userEvent.click(form.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.command).toHaveBeenCalled());
    expect(api.command.mock.calls[0][0].input.fact_ids).toEqual(["f1"]);
  });
  it("keeps the exact original timestamp when correcting only the outcome explanation", async () => {
    const { ApplicationForm } = await feature("workflow.tsx");
    const command = vi.fn().mockResolvedValue({ data: {} });
    const application = {
      id: "a1",
      revision: 1,
      job_version_id: "j1",
      preparation_id: null,
      resume_version_id: null,
      channel: "官网",
      outcome: "submitted",
      submitted_at: "2026-11-05T00:01:23.456Z",
      evidence: { statement: "原声明", asset_ids: ["e1"] },
    };
    render(
      <ApplicationForm
        api={{ command }}
        opp={{ id: "o1", preparations: [] }}
        application={application}
        jds={[{ value: "j1", label: "岗位" }]}
        resumes={[]}
        refresh={() => {}}
      />,
    );
    await userEvent.type(await screen.findByLabelText("纠正原因"), "补充描述");
    await userEvent.click(screen.getByRole("button", { name: "保存纠正" }));
    await waitFor(() => expect(command).toHaveBeenCalled());
    expect(command.mock.calls[0][0].input.submitted_at).toBe(
      application.submitted_at,
    );
    expect(command.mock.calls[0][0].input.evidence.asset_ids).toEqual(["e1"]);
  });
  it("retains fact dates and organization when correcting its visible description", async () => {
    const { ProfilePage } = await feature("profile.tsx");
    const content = {
      title: "经历",
      description: "原文",
      start_date: "2020-01-01",
      end_date: "2021-01-01",
      organization: "原公司",
      result: "原成果",
    };
    const api = {
      query: vi
        .fn()
        .mockResolvedValue({
          targets: [],
          facts: [
            {
              id: "fact-preserve",
              revision: 1,
              kind: "employment",
              status: "confirmed",
              content,
            },
          ],
          materials: [],
        }),
      command: vi.fn().mockResolvedValue({ data: {} }),
    };
    render(<ProfilePage api={api} revision={0} refresh={() => {}} />);
    await userEvent.click(await screen.findByText("经历 · 已确认"));
    const { within } = await import("@testing-library/react");
    const form = within(screen.getByRole("form", { name: "修订经历" }));
    await userEvent.type(await form.findByLabelText("经历原文"), "补充");
    await userEvent.click(form.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.command).toHaveBeenCalled());
    expect(api.command.mock.calls[0][0].input.content).toEqual({
      ...content,
      description: "原文补充",
    });
  });
  it("preserves structured criteria when editing the target's visible fields", async () => {
    const { ProfilePage } = await feature("profile.tsx");
    const condition = {
      field: "salary",
      operator: "gte",
      value: { amount: 20000, currency: "CNY", period: "month" },
      importance: "must",
    };
    const api = {
      query: vi
        .fn()
        .mockResolvedValue({
          targets: [
            {
              id: "salary-target",
              revision: 1,
              label: "原目标",
              criteria: {
                keywords: ["Python"],
                any_city: true,
                conditions: [condition],
              },
            },
          ],
          facts: [],
          materials: [],
        }),
      command: vi.fn().mockResolvedValue({ data: {} }),
    };
    render(<ProfilePage api={api} revision={0} refresh={() => {}} />);
    await userEvent.click(await screen.findByText(/原目标 · Python/));
    const { within } = await import("@testing-library/react");
    const form = within(screen.getByRole("form", { name: "编辑目标" }));
    const label = await form.findByLabelText("目标名称");
    await userEvent.clear(label);
    await userEvent.type(label, "修改名称");
    await userEvent.click(form.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(api.command).toHaveBeenCalled());
    expect(api.command.mock.calls[0][0].input.criteria.conditions).toEqual([
      condition,
    ]);
  });
  it("starts with real empty data, saves a target, and offers manual import when sources are unavailable", async () => {
    const { App } = await feature("App.tsx");
    const profile = { targets: [], facts: [], materials: [] };
    const api = {
      query: vi.fn(async (path: string) =>
        path === "profile" ? profile : { items: [], next_cursor: null },
      ),
      command: vi.fn(async (envelope: any) => {
        if (envelope.command === "SaveTarget")
          profile.targets.push({
            id: "target",
            revision: 1,
            ...envelope.input,
          } as never);
        return { data: { id: "new-job" } };
      }),
    };
    history.replaceState(null, "", "/?page=profile");
    render(<App api={api} />);
    await userEvent.type(await screen.findByLabelText("目标名称"), "后端方向");
    await userEvent.type(screen.getByLabelText("岗位关键词"), "Python, 后端");
    await userEvent.selectOptions(screen.getByLabelText("城市范围"), "any");
    await userEvent.click(screen.getByRole("button", { name: "保存目标" }));
    await waitFor(() => expect(api.command).toHaveBeenCalled());
    expect(api.command.mock.calls[0][0].input.criteria).toMatchObject({
      keywords: ["Python", "后端"],
      any_city: true,
      cities: [],
    });
    await userEvent.click(screen.getByRole("link", { name: "岗位" }));
    expect(await screen.findByText(/尚未接入来源搜索/)).toBeTruthy();
    await userEvent.type(await screen.findByLabelText("岗位名称"), "工程师");
    await userEvent.type(screen.getByLabelText("公司名称"), "示例公司");
    await userEvent.click(screen.getByRole("button", { name: "导入岗位" }));
    await waitFor(() => expect(api.command).toHaveBeenCalledTimes(2));
    expect(api.command.mock.calls[1][0].input).toEqual({
      text_fields: { title: "工程师", company: "示例公司", locations: [] },
    });
  });
});

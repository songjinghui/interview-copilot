import React from "react";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { beforeAll, afterAll, it, expect } from "vitest";
import {
  render,
  screen,
  within,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Api } from "../src/api";
import { App } from "../src/App";
import type { Page, Opportunity } from "../src/types";

let server: ChildProcessWithoutNullStreams;
let api: Api;
beforeAll(async () => {
  server = spawn("python", ["-X", "utf8", "tests/live_server.py"], {
    stdio: "pipe",
  });
  const connection = await new Promise<{ origin: string; nonce: string }>(
    (resolve, reject) => {
      let output = "";
      server.stdout.on("data", (data) => {
        output += data.toString();
        if (output.includes("\n")) resolve(JSON.parse(output.split("\n")[0]));
      });
      server.stderr.on("data", (data) => reject(new Error(data.toString())));
      server.on("error", reject);
      server.on("exit", (code) => {
        if (code) reject(new Error("Fixture exited " + code));
      });
    },
  );
  history.replaceState(
    null,
    "",
    "/?page=profile#bootstrap=" + connection.nonce,
  );
  api = new Api((path, options) =>
    fetch(connection.origin + path, {
      ...options,
      headers: { ...options?.headers, Origin: connection.origin },
    }),
  );
  await api.connect();
}, 15000);
afterAll(async () => {
  if (!server) return;
  server.stdin.end("\n");
  await new Promise<void>((resolve) => server.once("exit", () => resolve()));
}, 15000);

it("persists the complete manual journey through the real HTTP adapter and reloads its outcome", async () => {
  const user = userEvent.setup();
  const mounted = render(<App api={api} />);
  await user.type(await screen.findByLabelText("目标名称"), "后端研发");
  await user.type(screen.getByLabelText("岗位关键词"), "Python");
  await user.selectOptions(screen.getByLabelText("城市范围"), "any");
  await user.click(screen.getByRole("button", { name: "保存目标" }));
  await screen.findByText(/后端研发 · Python/);
  await user.type(await screen.findByLabelText("简历名称"), "工作简历");
  await user.type(
    screen.getByLabelText("简历正文"),
    "我做过 Python 服务开发。",
  );
  await user.click(screen.getByRole("button", { name: "保存简历" }));
  await screen.findByText("工作简历 · 最新 v1");
  await user.click(screen.getByRole("link", { name: "岗位" }));
  await user.type(await screen.findByLabelText("岗位名称"), "后端工程师");
  await user.type(screen.getByLabelText("公司名称"), "隔离测试公司");
  await user.type(screen.getByLabelText("岗位职责原文"), "开发服务");
  await user.type(screen.getByLabelText("任职要求原文"), "熟悉 Python");
  await user.click(screen.getByRole("button", { name: "导入岗位" }));
  await user.click(await screen.findByRole("button", { name: /后端工程师/ }));
  await user.click(await screen.findByRole("button", { name: "加入机会" }));
  await user.click(await screen.findByText("补充或纠正依据"));
  const cooldown = within(screen.getByRole("form", { name: "冷却期说明" }));
  await user.selectOptions(
    await cooldown.findByLabelText("冷却期状态"),
    "present",
  );
  await user.type(cooldown.getByLabelText("冷却期说明"), "招聘方提醒");
  await user.type(cooldown.getByLabelText("依据原文"), "再次投递有冷却期");
  await user.click(cooldown.getByRole("button", { name: "保存" }));
  await screen.findByText("有冷却期 · 招聘方提醒");
  const jd = (await screen.findByLabelText(
    "固定 JD 版本",
  )) as HTMLSelectElement;
  await user.selectOptions(jd, jd.options[1].value);
  const resume = screen.getByLabelText("固定简历版本") as HTMLSelectElement;
  await waitFor(() => expect(resume.options.length).toBe(2));
  await user.selectOptions(resume, resume.options[1].value);
  await user.type(screen.getByLabelText("投递渠道"), "官网");
  await user.click(screen.getByRole("button", { name: "保存准备材料" }));
  await user.click(await screen.findByRole("button", { name: "确认材料" }));
  await user.click(
    await screen.findByRole("button", { name: "确认了解冷却期，仍自行投递" }),
  );
  await screen.findByText(/材料已确认，可自行投递/);
  const opportunities = await api.query<Page<Opportunity>>("opportunities");
  let detail = await api.query<Opportunity>(
    "opportunities/" + opportunities.items[0].id,
  );
  expect(detail.applications).toEqual([]);
  await user.click(screen.getByText("补记实际结果（含历史投递）"));
  const form = within(screen.getByRole("form", { name: "记录实际结果" }));
  await user.selectOptions(
    await form.findByLabelText("实际使用 JD"),
    detail.jobs[0].current_version.id,
  );
  await user.selectOptions(
    form.getByLabelText("实际使用简历"),
    detail.preparations[0].resume_version_id!,
  );
  await user.selectOptions(
    form.getByLabelText("关联准备（可选）"),
    detail.preparations[0].id,
  );
  await user.type(form.getByLabelText("实际投递渠道"), "官网");
  await user.selectOptions(form.getByLabelText("实际结果"), "submitted");
  fireEvent.change(form.getByLabelText("实际提交时间"), {
    target: { value: "2026-11-05T13:30" },
  });
  await user.type(form.getByLabelText("结果依据"), "本人看到提交成功页");
  await user.click(form.getByRole("button", { name: "保存实际结果" }));
  await screen.findByText(/已提交 · 官网/);
  mounted.unmount();
  render(<App api={api} />);
  await screen.findByText(/已提交 · 官网/);
  detail = await api.query<Opportunity>("opportunities/" + detail.id);
  expect(detail.applications).toHaveLength(1);
  expect(detail.applications[0].events).toHaveLength(1);
}, 20000);

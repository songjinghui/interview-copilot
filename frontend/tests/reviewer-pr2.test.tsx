import React from "react";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { beforeAll, afterAll, it, expect } from "vitest";
import { render, screen, within, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Api } from "../src/api";
import { App } from "../src/App";
let server: ChildProcessWithoutNullStreams;
let api: Api;
beforeAll(async () => {
  server = spawn("python", ["-X", "utf8", "tests/live_server.py"], {stdio:"pipe"});
  const info = await new Promise<{origin:string;nonce:string}>((resolve,reject) => {
    let output="";
    server.stdout.on("data", data => { output+=data.toString(); if(output.includes("\n")) resolve(JSON.parse(output.split("\n")[0])); });
    server.stderr.on("data", data => reject(new Error(data.toString())));
    server.on("error", reject);
  });
  history.replaceState(null,"","/#bootstrap="+info.nonce);
  api=new Api((path,options)=>fetch(info.origin+path,{...options,headers:{...options?.headers, Origin:info.origin}}));
  await api.connect();
},15000);
afterAll(async () => { if(server){ server.stdin.end("\n"); await new Promise<void>(resolve=>server.once("exit",()=>resolve())); } },15000);
const command=async(name:string,input:any,revision?:number)=>(await api.command({command:name,input,request_id:crypto.randomUUID(),...(revision===undefined?{}:{expected_revision:revision})})).data as any;

it("W1: stale confirmation must not confirm an unseen replacement resume", async () => {
  const job=await command("ImportJob",{text_fields:{title:"Review JD",company:"Synthetic Co",responsibilities:"Work",requirements:"Skills"}});
  const opp=await command("SaveOpportunity",{job_id:job.id});
  const oldResume=await command("ImportMaterial",{label:"Old resume",text:"OLD RESUME VISIBLE"});
  const newResume=await command("ImportMaterial",{label:"New resume",text:"NEW RESUME MUST BE REVIEWED"});
  const prepInput={opportunity_id:opp.id,job_version_id:job.current_version.id,resume_version_id:oldResume.id,channel:"manual"};
  const prep=await command("SavePreparation",prepInput);
  history.replaceState(null,"","/?page=opportunities&id="+opp.id);
  render(<App api={api}/>);
  await screen.findByText("OLD RESUME VISIBLE");
  await command("SavePreparation",{...prepInput,id:prep.id,resume_version_id:newResume.id},prep.revision);
  await userEvent.click(await screen.findByRole("button",{name:"确认材料"}));
  const updatedResume=await screen.findByText("NEW RESUME MUST BE REVIEWED");
  expect(updatedResume).toBeTruthy();
  const afterConflict=await api.query<any>("preparations/"+prep.id);
  expect(afterConflict.revision).toBe(2);
  expect(afterConflict.next_step).toBe("materials");
  await userEvent.click(screen.getByRole("button",{name:"确认材料"}));
  await waitFor(async()=>expect((await api.query<any>("preparations/"+prep.id)).revision).toBe(3));
  const saved=await api.query<any>("preparations/"+prep.id);
  expect(saved.resume_version_id).toBe(newResume.id);
  expect(saved.next_step).toBe("manual_apply");
},15000);

it("W2: changing only target label must preserve commas inside a stored condition",async()=>{
  const conditions=[{field:"description",operator:"contains",value:"研发，平台",importance:"must"}];
  const target=await command("SaveTarget",{label:"Comma condition",criteria:{keywords:["Python"],any_city:true,conditions}});
  history.replaceState(null,"","/?page=profile");
  render(<App api={api}/>);
  await userEvent.click(await screen.findByText(/Comma condition · Python/));
  const form=within(screen.getByRole("form",{name:"编辑目标"}));
  fireEvent.change(await form.findByLabelText("目标名称"),{target:{value:"Renamed"}});
  await userEvent.click(form.getByRole("button",{name:"保存"}));
  await screen.findByText(/Renamed · Python/);
  const profile=await api.query<any>("profile");
  expect(profile.targets.find((t:any)=>t.id===target.id).criteria.conditions).toEqual(conditions);
},15000);

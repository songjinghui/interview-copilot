import React, { useEffect, useRef, useState } from "react";
import { ActionForm } from "./forms";
import { ProfilePage, split } from "./profile";
import { useQuery } from "./query";
import { safeLink } from "./api";
import { OpportunityPage } from "./workflow";
import { Dashboard } from "./Dashboard";
import type { ApiPort, Job, Page, Opportunity } from "./types";
const names: Record<string, string> = {
  dashboard: "总览",
  profile: "目标与资料",
  jobs: "岗位",
  opportunities: "投递机会",
};
function route() {
  const params = new URLSearchParams(location.search);
  return { page: params.get("page") ?? "dashboard", id: params.get("id") ?? "" };
}
export function App({ api }: { api: ApiPort }) {
  const [locationState, setLocation] = useState(route),
    [revision, setRevision] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = () => setRevision((v) => v + 1);
  function navigate(page: string, id = "") {
    history.pushState(
      null,
      "",
      `?page=${page}${id ? "&id=" + encodeURIComponent(id) : ""}`,
    );
    setLocation({ page, id });
  }
  useEffect(() => {
    const update = () => setLocation(route());
    addEventListener("popstate", update);
    return () => removeEventListener("popstate", update);
  }, []);
  useEffect(() => {
    heading.current?.focus();
  }, [locationState.page, locationState.id]);
  const page = names[locationState.page] ? locationState.page : "dashboard";
  return (
    <div className="shell">
      <a className="skip" href="#main">
        跳到内容
      </a>
      <aside className="navigation">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            +
          </span>
          <div className="brand-copy">
            <strong>求职工作台</strong>
            <small>JOB SEARCH WORKSPACE</small>
          </div>
        </div>
        <nav aria-label="工作台">
          {Object.entries(names).map(([key, label]) => (
            <a
              key={key}
              href={`?page=${key}`}
              aria-current={page === key ? "page" : undefined}
              onClick={(event) => {
                event.preventDefault();
                navigate(key);
              }}
            >
              {label}
            </a>
          ))}
        </nav>
        <p className="local-note">
          <span className="local-note-mark" aria-hidden="true">
            我
          </span>
          <span>
            <strong>本机工作空间</strong>
            <small>资料仅保存在你的设备</small>
          </span>
        </p>
      </aside>
      <main id="main">
        {page === "dashboard" ? (
          <Dashboard
            api={api}
            revision={revision}
            navigate={navigate}
            headingRef={heading}
          />
        ) : (
          <>
            <header className="page-header">
              <div>
                <p className="eyebrow">工作空间</p>
                <h1 ref={heading} tabIndex={-1}>
                  {names[page]}
                </h1>
              </div>
              <button className="secondary" onClick={refresh}>
                刷新记录
              </button>
            </header>
            {page === "profile" ? (
              <ProfilePage api={api} revision={revision} refresh={refresh} />
            ) : page === "jobs" ? (
              <JobsPage
                api={api}
                revision={revision}
                refresh={refresh}
                selected={locationState.id}
                navigate={navigate}
              />
            ) : (
              <OpportunityPage
                api={api}
                revision={revision}
                refresh={refresh}
                selected={locationState.id}
                navigate={navigate}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
function JobsPage({
  api,
  revision,
  refresh,
  selected,
  navigate,
}: {
  api: ApiPort;
  revision: number;
  refresh: () => void;
  selected: string;
  navigate: (page: string, id?: string) => void;
}) {
  const [filter, setFilter] = useState(""),
    [cursor, setCursor] = useState("");
  const { data, error, loading } = useQuery<Page<Job>>(
    api,
    "jobs?query=" +
      encodeURIComponent(filter) +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    revision,
  );
  const sources = useQuery<Page<unknown>>(api, "sources", revision);
  return (
    <div className="split-view">
      <section className="record-list" aria-label="岗位列表">
        <label>
          筛选岗位
          <input
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setCursor("");
            }}
          />
        </label>
        {loading && <p role="status">正在读取岗位…</p>}
        {error && (
          <p role="alert" className="error">
            {error.message}
          </p>
        )}
        {data && !data.items.length && (
          <p className="empty">还没有符合条件的岗位。可以在右侧粘贴 JD。</p>
        )}
        {data?.items.map((job) => (
          <button
            className="row-button"
            key={job.id}
            aria-current={selected === job.id ? "true" : undefined}
            onClick={() => navigate("jobs", job.id)}
          >
            <strong>{job.current_version.title}</strong>
            <span>{job.current_version.company_name}</span>
            <small>
              {job.source_key === "manual" ? "手工导入" : job.source_key} ·{" "}
              {job.current_version.completeness === "complete"
                ? "JD 完整"
                : "JD 待补充"}
            </small>
          </button>
        ))}
        <div className="actions">
          {cursor && (
            <button className="secondary" onClick={() => setCursor("")}>
              回到第一页
            </button>
          )}
          {data?.next_cursor && (
            <button
              className="secondary"
              onClick={() => setCursor(data.next_cursor!)}
            >
              下一页
            </button>
          )}
        </div>
        {selected && (
          <button onClick={() => navigate("jobs")}>导入新岗位</button>
        )}
      </section>
      <div className="detail-panel">
        {sources.error && <p role="alert">{sources.error.message}</p>}
        {sources.data && !sources.data.items.length && (
          <p className="notice">
            尚未接入来源搜索，可先手工导入岗位原文。后续按需要增加来源。
          </p>
        )}
        {selected ? (
          <JobDetail
            api={api}
            id={selected}
            revision={revision}
            navigate={navigate}
          />
        ) : (
          <>
            <h2>保存一个值得了解的岗位</h2>
            <p className="muted">
              只填你实际拿到的信息。缺失的职责、要求会标为待补充。
            </p>
            <ActionForm
              id="new-job"
              title="手工导入"
              api={api}
              command="ImportJob"
              submitLabel="导入岗位"
              onSaved={refresh}
              fields={[
                { name: "title", label: "岗位名称", required: true },
                { name: "company", label: "公司名称", required: true },
                { name: "url", label: "原始链接", type: "url" },
                { name: "locations", label: "岗位城市" },
                { name: "salary_raw", label: "薪资原文" },
                {
                  name: "responsibilities",
                  label: "岗位职责原文",
                  multiline: true,
                },
                {
                  name: "requirements",
                  label: "任职要求原文",
                  multiline: true,
                },
              ]}
              input={(v) => ({
                text_fields: {
                  title: v.title,
                  company: v.company,
                  locations: split(v.locations),
                  ...Object.fromEntries(
                    ["url", "salary_raw", "responsibilities", "requirements"]
                      .filter((k) => v[k]?.trim())
                      .map((k) => [k, v[k]]),
                  ),
                },
              })}
            />
          </>
        )}
      </div>
    </div>
  );
}
function JobDetail({
  api,
  id,
  revision,
  navigate,
}: {
  api: ApiPort;
  id: string;
  revision: number;
  navigate: (page: string, id?: string) => void;
}) {
  const { data, error, loading } = useQuery<Job>(api, "jobs/" + id, revision);
  if (error)
    return (
      <p role="alert" className="error">
        {error.message}
      </p>
    );
  if (loading || !data) return <p role="status">正在读取 JD…</p>;
  const version = data.current_version,
    href = safeLink(version.original_url);
  return (
    <>
      <p className="eyebrow">
        {data.source_key === "manual" ? "手工录入" : data.source_key} · 当前 v
        {version.revision}
      </p>
      <h2>{version.title}</h2>
      <p>
        {version.company_name} · {version.locations?.join("、") || "城市未知"}
      </p>
      <p>{version.salary_text || "薪资未知"}</p>
      {href && (
        <a href={href} target="_blank" rel="noopener noreferrer">
          查看原始链接
        </a>
      )}
      <h3>岗位职责</h3>
      <p className="raw">{version.description_text || "未知，尚未取得原文"}</p>
      <h3>任职要求</h3>
      <p className="raw">{version.requirements_text || "未知，尚未取得原文"}</p>
      {data.last_complete_version &&
        data.last_complete_version.id !== version.id && (
          <details>
            <summary>
              历史完整 JD v{data.last_complete_version.revision}（非当前）
            </summary>
            <p className="raw">{data.last_complete_version.description_text}</p>
            <p className="raw">
              {data.last_complete_version.requirements_text}
            </p>
          </details>
        )}
      <ActionForm
        id={`save-opportunity-${id}`}
        title="纳入求职进度"
        fields={[]}
        api={api}
        command="SaveOpportunity"
        input={() => ({ job_id: id })}
        onSaved={(record) => navigate("opportunities", String(record.id))}
        submitLabel="加入机会"
      />
    </>
  );
}

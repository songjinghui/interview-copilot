import React, { useEffect, useState } from "react";
import { ActionForm, type Field } from "./forms";
import { Preparation } from "./opportunities";
import { allPages, useQuery } from "./query";
import type {
  ApiPort,
  Application,
  Job,
  MaterialVersion,
  Opportunity,
  Page,
  Prep,
  Profile,
} from "./types";
const statuses: Record<string, string> = {
  saved: "已收藏",
  deferred: "暂缓",
  applying: "准备中",
  applied: "已投递",
  interviewing: "面试中",
  offer: "收到 Offer",
  rejected: "未通过",
  withdrawn: "已撤回",
  archived: "已归档",
};
const outcomes: Record<string, string> = {
  submitted: "已提交",
  unknown: "结果不确定",
  failed: "提交失败",
};
const statusOptions = Object.entries(statuses).map(([value, label]) => ({
  value,
  label,
}));
type Navigate = (page: string, id?: string) => void;
export function OpportunityPage({
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
  navigate: Navigate;
}) {
  const [status, setStatus] = useState(""),
    [filter, setFilter] = useState(""),
    [cursor, setCursor] = useState("");
  const result = useQuery<Page<Opportunity>>(
    api,
    `opportunities?status=${status}&query=${encodeURIComponent(filter)}` +
      (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    revision,
  );
  return (
    <div className="split-view">
      <section className="record-list" aria-label="机会列表">
        <label>
          筛选机会
          <input
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setCursor("");
            }}
          />
        </label>
        <label>
          进展
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setCursor("");
            }}
          >
            <option value="">全部进展</option>
            {statusOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {result.loading && <p role="status">正在读取机会…</p>}
        {result.error && (
          <p role="alert" className="error">
            {result.error.message}
          </p>
        )}
        {result.data && !result.data.items.length && (
          <p className="empty">
            还没有符合条件的机会。可以从岗位加入，也可直接补录。
          </p>
        )}
        {result.data?.items.map((opp) => (
          <button
            key={opp.id}
            className="row-button"
            aria-current={selected === opp.id ? "true" : undefined}
            onClick={() => navigate("opportunities", opp.id)}
          >
            <strong>{opp.title}</strong>
            <span>{opp.company_name}</span>
            <small>{statuses[opp.status]}</small>
          </button>
        ))}
        <div className="actions">
          {cursor && (
            <button className="secondary" onClick={() => setCursor("")}>
              回到第一页
            </button>
          )}
          {result.data?.next_cursor && (
            <button
              className="secondary"
              onClick={() => setCursor(result.data!.next_cursor!)}
            >
              下一页
            </button>
          )}
        </div>
        {selected && (
          <button onClick={() => navigate("opportunities")}>
            补录其他机会
          </button>
        )}
      </section>
      <div className="detail-panel">
        {selected ? (
          <OpportunityDetail
            api={api}
            id={selected}
            revision={revision}
            refresh={refresh}
          />
        ) : (
          <>
            <h2>让每一次沟通都有记录</h2>
            <p className="muted">
              已经开始沟通、还没有完整 JD，也可以先补录机会。
            </p>
            <ActionForm
              id="new-opportunity"
              title="直接补录机会"
              fields={[
                { name: "title", label: "机会名称", required: true },
                { name: "company_name", label: "公司名称", required: true },
              ]}
              api={api}
              command="SaveOpportunity"
              input={(v) => v}
              onSaved={(value) => {
                refresh();
                navigate("opportunities", String(value.id));
              }}
              submitLabel="保存机会"
            />
          </>
        )}
      </div>
    </div>
  );
}
function OpportunityDetail({
  api,
  id,
  revision,
  refresh,
}: {
  api: ApiPort;
  id: string;
  revision: number;
  refresh: () => void;
}) {
  const result = useQuery<Opportunity>(api, "opportunities/" + id, revision);
  const profile = useQuery<Profile>(api, "profile", revision);
  const [jobs, setJobs] = useState<Job[]>([]),
    [resumes, setResumes] = useState<{ value: string; label: string }[]>([]),
    [choicesError, setChoicesError] = useState("");
  useEffect(() => {
    let active = true;
    setChoicesError("");
    allPages<Job>(api, "jobs")
      .then((value) => {
        if (active) setJobs(value);
      })
      .catch(() => {
        if (active) setChoicesError("岗位选项读取失败，请刷新后重试");
      });
    return () => {
      active = false;
    };
  }, [api, revision]);
  useEffect(() => {
    let active = true;
    if (profile.data) {
      Promise.all(
        profile.data.materials.map(async (material) => {
          const versions = await allPages<MaterialVersion>(
            api,
            `materials/${material.id}/versions`,
          );
          return versions.map((v) => ({
            value: v.id,
            label: `${material.label} · v${v.revision}`,
          }));
        }),
      )
        .then((value) => {
          if (active) setResumes(value.flat());
        })
        .catch(() => {
          if (active) setChoicesError("简历版本读取失败，请刷新后重试");
        });
    }
    return () => {
      active = false;
    };
  }, [api, profile.data]);
  if (result.error)
    return (
      <p role="alert" className="error">
        {result.error.message}
      </p>
    );
  if (!result.data) return <p role="status">正在读取机会…</p>;
  const opp = result.data;
  const jdOptions = opp.jobs.flatMap((job) =>
    job.versions.map((v) => ({
      value: v.id,
      label: `${v.title} · ${job.source_key === "manual" ? "手工导入" : job.source_key} · JD v${v.revision}`,
    })),
  );
  const jobOptions = jobs
    .filter((job) => !opp.jobs.some((link) => link.id === job.id))
    .map((job) => ({
      value: job.id,
      label: `${job.current_version.title} · ${job.current_version.company_name}`,
    }));
  return (
    <>
      <p className="eyebrow">{statuses[opp.status]}</p>
      <h2>{opp.title}</h2>
      <p>{opp.company_name}</p>
      <details>
        <summary>进展与备注</summary>
        <ActionForm
          key={opp.revision}
          id={`opportunity-${opp.id}`}
          title="编辑机会"
          fields={[
            { name: "title", label: "机会名称", required: true },
            {
              name: "status",
              label: "机会进展",
              required: true,
              options: statusOptions,
            },
            { name: "note", label: "备注", multiline: true },
          ]}
          initial={{
            title: opp.title,
            status: opp.status,
            note: opp.note ?? "",
          }}
          api={api}
          command="UpdateOpportunity"
          expected={opp.revision}
          input={(v) => ({ id: opp.id, ...v })}
          onSaved={refresh}
        />
      </details>
      <section>
        <h3>关联岗位</h3>
        {!opp.jobs.length && (
          <p className="notice">
            请先关联岗位，再选择 JD 准备材料。可在“岗位”中粘贴原文。
          </p>
        )}
        {opp.jobs.map((job) => (
          <details key={job.id}>
            <summary>
              {job.current_version.title} · 当前 v{job.current_version.revision}
            </summary>
            <p className="raw">
              {job.current_version.description_text || "职责未知"}
            </p>
            <p className="raw">
              {job.current_version.requirements_text || "要求未知"}
            </p>
            <ActionForm
              id={`unlink-${opp.id}-${job.id}-${opp.revision}`}
              title=""
              fields={[]}
              api={api}
              command="UnlinkJob"
              expected={opp.revision}
              input={() => ({
                opportunity_id: opp.id,
                job_id: job.id,
                basis: {
                  kind: "user_confirmed",
                  description: "用户在机会页解除关联",
                },
              })}
              onSaved={refresh}
              onConflict={refresh}
              submitLabel="解除关联（未使用的准备需重新确认）"
            />
          </details>
        ))}
        {choicesError && (
          <p role="alert" className="error">
            {choicesError}
          </p>
        )}
        {jobOptions.length > 0 && (
          <ActionForm
            key={opp.revision}
            id={`link-${opp.id}`}
            title="关联另一条岗位"
            fields={[
              {
                name: "job_id",
                label: "选择已保存岗位",
                required: true,
                options: jobOptions,
              },
            ]}
            api={api}
            command="LinkJob"
            expected={opp.revision}
            input={(v) => ({
              opportunity_id: opp.id,
              job_id: v.job_id,
              basis: {
                kind: "user_confirmed",
                description: "用户核对为同一机会",
              },
            })}
            onSaved={refresh}
            submitLabel="确认关联"
          />
        )}
      </section>
      <section>
        <h3>冷却期</h3>
        <p>
          {opp.cooldown.status === "present"
            ? "有冷却期"
            : opp.cooldown.status === "absent"
              ? "无冷却期"
              : "待核实"}{" "}
          · {opp.cooldown.explanation}
        </p>
        <details>
          <summary>补充或纠正依据</summary>
          <ActionForm
            key={opp.revision}
            id={`cooldown-${opp.id}`}
            title="冷却期说明"
            fields={[
              {
                name: "status",
                label: "冷却期状态",
                required: true,
                options: [
                  { value: "unknown", label: "待核实" },
                  { value: "present", label: "有冷却期" },
                  { value: "absent", label: "无冷却期" },
                ],
              },
              { name: "explanation", label: "冷却期说明", required: true },
              {
                name: "evidence",
                label: "依据原文",
                multiline: true,
                help: "有或无冷却期时必填，例如招聘方明确说明；不自动推算到期",
              },
            ]}
            api={api}
            command="RecordCooldown"
            expected={opp.revision}
            input={(v) => ({
              opportunity_id: opp.id,
              scope: "job",
              status: v.status,
              explanation: v.explanation,
              evidence: {
                items: v.evidence?.trim()
                  ? [{ kind: "user", text: v.evidence }]
                  : [],
              },
            })}
            onSaved={refresh}
          />
        </details>
      </section>
      <section>
        <h3>准备材料</h3>
        {opp.preparations.map((prep) => (
          <div key={prep.id}>
            <Preparation prep={prep} api={api} refresh={refresh} />
            {jdOptions.length > 0 && (
              <details>
                <summary>修改选材或继续暂缓的准备</summary>
                <PreparationForm
                  api={api}
                  opp={opp}
                  prep={prep}
                  jds={jdOptions}
                  resumes={resumes}
                  refresh={refresh}
                />
              </details>
            )}
          </div>
        ))}
        {jdOptions.length > 0 && !choicesError && (
          <details open={!opp.preparations.length}>
            <summary>新增一份准备</summary>
            <PreparationForm
              api={api}
              opp={opp}
              jds={jdOptions}
              resumes={resumes}
              refresh={refresh}
            />
          </details>
        )}
      </section>
      <section>
        <h3>实际投递记录</h3>
        <p className="muted">
          只记录你已发生的操作。打开外链和确认材料都不会自动记为已提交。
        </p>
        {!opp.applications.length && <p>尚未记录实际结果。</p>}
        {opp.applications.map((application) => (
          <details key={application.id}>
            <summary>
              {outcomes[application.outcome]} · {application.channel} ·{" "}
              {application.submitted_at
                ? new Date(application.submitted_at).toLocaleString()
                : "提交时间未知"}
            </summary>
            <p className="raw">{application.evidence.statement}</p>
            <ol className="history">
              {application.events.map((event) => (
                <li key={event.revision}>
                  v{event.revision} · {event.reason} ·{" "}
                  {new Date(event.recorded_at).toLocaleString()}
                </li>
              ))}
            </ol>
            <ApplicationForm
              api={api}
              opp={opp}
              application={application}
              jds={jdOptions}
              resumes={resumes}
              refresh={refresh}
            />
          </details>
        ))}
        {jdOptions.length > 0 && !choicesError && (
          <details>
            <summary>补记实际结果（含历史投递）</summary>
            <ApplicationForm
              api={api}
              opp={opp}
              jds={jdOptions}
              resumes={resumes}
              refresh={refresh}
            />
          </details>
        )}
      </section>
    </>
  );
}
type Option = { value: string; label: string };
function PreparationForm({
  api,
  opp,
  prep,
  jds,
  resumes,
  refresh,
}: {
  api: ApiPort;
  opp: Opportunity;
  prep?: Prep;
  jds: Option[];
  resumes: Option[];
  refresh: () => void;
}) {
  const fields: Field[] = [
    {
      name: "job_version_id",
      label: "固定 JD 版本",
      required: true,
      options: jds,
    },
    { name: "resume_version_id", label: "固定简历版本", options: resumes },
    {
      name: "resume_exception",
      label: "此渠道无需简历的说明",
      help: "未选择简历时，必须明确说明无需材料的原因",
    },
    { name: "channel", label: "投递渠道", required: true },
    { name: "apply_url", label: "投递页面链接", type: "url" },
  ];
  return (
    <ActionForm
      key={prep?.revision ?? "new"}
      id={`preparation-${opp.id}-${prep?.id ?? "new"}`}
      title={prep ? "修改准备" : "选择本次材料"}
      fields={fields}
      api={api}
      command="SavePreparation"
      expected={prep?.revision}
      initial={
        prep
          ? {
              job_version_id: prep.job_version_id,
              resume_version_id: prep.resume_version_id ?? "",
              resume_exception: prep.resume_exception ?? "",
              channel: prep.channel,
              apply_url: prep.apply_url ?? "",
            }
          : {}
      }
      input={(v) => ({
        ...(prep ? { id: prep.id } : {}),
        opportunity_id: opp.id,
        job_version_id: v.job_version_id,
        resume_version_id: v.resume_version_id || null,
        resume_exception: v.resume_exception || null,
        channel: v.channel,
        apply_url: v.apply_url || null,
      })}
      onSaved={refresh}
      submitLabel="保存准备材料"
    />
  );
}
export function ApplicationForm({
  api,
  opp,
  application,
  jds,
  resumes,
  refresh,
}: {
  api: ApiPort;
  opp: Opportunity;
  application?: Application;
  jds: Option[];
  resumes: Option[];
  refresh: () => void;
}) {
  const versions =
    application && !jds.some((jd) => jd.value === application.job_version_id)
      ? [
          {
            value: application.job_version_id,
            label: "原申请 JD（保留固定版本）",
          },
          ...jds,
        ]
      : jds;
  const fields: Field[] = [
    {
      name: "job_version_id",
      label: "实际使用 JD",
      required: true,
      options: versions,
    },
    { name: "resume_version_id", label: "实际使用简历", options: resumes },
    {
      name: "preparation_id",
      label: "关联准备（可选）",
      options: opp.preparations.map((prep) => ({
        value: prep.id,
        label: `${prep.job.title} · JD v${prep.job.revision} · ${prep.channel}`,
      })),
    },
    { name: "channel", label: "实际投递渠道", required: true },
    {
      name: "outcome",
      label: "实际结果",
      required: true,
      options: Object.entries(outcomes).map(([value, label]) => ({
        value,
        label,
      })),
    },
    {
      name: "submitted_at",
      label: "实际提交时间",
      type: "datetime-local",
      help: "已提交时必填，按当前电脑时区输入",
    },
    { name: "statement", label: "结果依据", required: true, multiline: true },
    ...(application
      ? [{ name: "reason", label: "纠正原因", required: true }]
      : []),
  ];
  let localTime = "";
  if (application?.submitted_at) {
    const date = new Date(application.submitted_at);
    localTime = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
      .toISOString()
      .slice(0, 16);
  }
  return (
    <ActionForm
      key={application?.revision ?? "new"}
      id={`application-${opp.id}-${application?.id ?? "new"}`}
      title={application ? "纠正记录（保留历史）" : "记录实际结果"}
      fields={fields}
      api={api}
      command="RecordApplication"
      expected={application?.revision}
      initial={
        application
          ? {
              job_version_id: application.job_version_id,
              resume_version_id: application.resume_version_id ?? "",
              preparation_id: application.preparation_id ?? "",
              channel: application.channel,
              outcome: application.outcome,
              submitted_at: localTime,
              statement: application.evidence.statement ?? "",
            }
          : {}
      }
      input={(v) => {
        if (v.outcome === "submitted" && !v.submitted_at)
          throw new Error("已提交必须填写实际提交时间");
        return {
          ...(application ? { id: application.id, reason: v.reason } : {}),
          opportunity_id: opp.id,
          job_version_id: v.job_version_id,
          resume_version_id: v.resume_version_id || null,
          preparation_id: v.preparation_id || null,
          channel: v.channel,
          outcome: v.outcome,
          submitted_at:
            application && v.submitted_at === localTime
              ? application.submitted_at
              : v.submitted_at
                ? new Date(v.submitted_at).toISOString()
                : null,
          evidence: {
            kind: "user_attestation",
            statement: v.statement,
            asset_ids: application?.evidence.asset_ids ?? [],
          },
        };
      }}
      onSaved={refresh}
      submitLabel={application ? "保存纠正" : "保存实际结果"}
    />
  );
}

import React, { useEffect, useState, type RefObject } from "react";
import { allPages } from "./query";
import type { ApiPort, Job, Opportunity, Profile } from "./types";

type Snapshot = { profile: Profile; jobs: Job[]; opportunities: Opportunity[] };
type Navigate = (page: string, id?: string) => void;

const statusLabels: Record<string, string> = {
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

export function Dashboard({
  api,
  revision,
  navigate,
  headingRef,
}: {
  api: ApiPort;
  revision: number;
  navigate: Navigate;
  headingRef: RefObject<HTMLHeadingElement | null>;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retryRevision, setRetryRevision] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setLoading(true);
    setError("");
    setSnapshot(null);
    Promise.all([
      api.query<Profile>("profile"),
      allPages<Job>(api, "jobs"),
      allPages<Opportunity>(api, "opportunities"),
    ])
      .then(([profile, jobs, opportunities]) => {
        if (active) setSnapshot({ profile, jobs, opportunities });
      })
      .catch((failure: unknown) => {
        if (active) {
          setError(
            (failure as Error).message || "读取工作台信息失败，请刷新重试。",
          );
          const code = (failure as { code?: string }).code;
          if (!code || code === "STORAGE_ERROR" || code === "BUSY") {
            const delay = [1000, 2000, 5000, 10000][Math.min(retryRevision, 3)];
            timer = setTimeout(
              () => setRetryRevision((current) => current + 1),
              delay,
            );
          }
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [api, revision, retryRevision]);

  const opportunities = snapshot?.opportunities ?? [];
  const hasSnapshot = snapshot !== null;
  const activeOpportunities = opportunities.filter(
    (item) => !["rejected", "withdrawn", "archived"].includes(item.status),
  );
  const preparing = opportunities.filter((item) =>
    ["saved", "applying"].includes(item.status),
  ).length;
  const interviewing = opportunities.filter((item) =>
    ["interviewing", "offer"].includes(item.status),
  ).length;
  const nextAction = !hasSnapshot
    ? null
    : !snapshot.profile.targets.some((target) => target.active)
      ? {
        label: "先整理求职方向",
        detail: "写下目标岗位、城市和不能妥协的条件，后续筛选与准备都能复用。",
        button: "完善求职目标",
        page: "profile",
      }
      : snapshot.jobs.length === 0
      ? {
          label: "开始积累岗位",
          detail: "导入你正在考虑的岗位，保留 JD 原文和来源，之后再决定是否推进。",
          button: "查看岗位",
          page: "jobs",
        }
      : {
          label: "推进一个值得了解的机会",
          detail: "核对岗位信息和进度；是否投递始终由你决定，助手只记录实际发生的事。",
          button: "查看投递机会",
          page: "opportunities",
        };

  return (
    <div className="dashboard-page">
      <section className="dashboard-hero">
        <p className="eyebrow">求职进度总览</p>
        <h1 id="dashboard-main" ref={headingRef} tabIndex={-1}>
          把求职进度，变得清晰可控。
        </h1>
        <p>从目标筛选到面试复盘，每一步都有记录。</p>
        <button onClick={() => navigate("profile")}>
          查看目标与资料
          <span aria-hidden="true"> →</span>
        </button>
      </section>

      {error && <p role="alert" className="error dashboard-error">{error}</p>}
      {loading && <p role="status" className="dashboard-loading">正在整理你的求职进度…</p>}
      {error && (
        <button className="secondary dashboard-retry" onClick={() => setRetryRevision((current) => current + 1)}>
          重试读取
        </button>
      )}

      <section className="dashboard-section" aria-labelledby="progress-title">
        <div className="section-heading">
          <h2 id="progress-title">当前进展</h2>
          <span className="muted">来自你保存的记录</span>
        </div>
        <div className="metric-grid">
          <article className="metric-card">
            <span className="metric-label">已收录岗位</span>
            <strong>{!hasSnapshot ? "—" : snapshot.jobs.length}</strong>
            <span className="metric-note">保留 JD 与来源信息</span>
          </article>
          <article className="metric-card metric-card-warm">
            <span className="metric-label">待推进机会</span>
            <strong>{!hasSnapshot ? "—" : preparing}</strong>
            <span className="metric-note">收藏或准备中的机会</span>
          </article>
          <article className="metric-card metric-card-cool">
            <span className="metric-label">面试与 Offer</span>
            <strong>{!hasSnapshot ? "—" : interviewing}</strong>
            <span className="metric-note">按当前记录的机会状态</span>
          </article>
        </div>
      </section>

      <div className="dashboard-columns">
        <section className="dashboard-section next-step">
          <div className="section-heading">
            <h2>接下来，先做这件事</h2>
          </div>
          <article className="next-card">
            {!nextAction ? (
              <>
                <div className="next-kicker"><span aria-hidden="true">i</span> 下一步建议</div>
                <h3>{error ? "暂时无法判断下一步" : "正在读取你的求职进度"}</h3>
                <p>{error ? "数据恢复后会重新整理建议；可使用上方“重试读取”，或先查看目标与资料。" : "读取已保存的目标与岗位后，这里会给出适合当前进度的建议。"}</p>
              </>
            ) : (
              <>
            <div className="next-kicker"><span aria-hidden="true">↗</span> 建议的下一步</div>
            <h3>{nextAction.label}</h3>
            <p>{nextAction.detail}</p>
            <button onClick={() => navigate(nextAction.page)}>{nextAction.button}<span aria-hidden="true"> →</span></button>
              </>
            )}
          </article>
        </section>

        <section className="dashboard-section recent-section">
          <div className="section-heading">
            <h2>最近机会</h2>
            <button className="text-button" onClick={() => navigate("opportunities")}>全部机会 <span aria-hidden="true">→</span></button>
          </div>
          {loading ? (
            <p role="status" className="muted">正在读取机会…</p>
          ) : !hasSnapshot ? (
            <div className="empty-card">
              <p>机会列表暂时无法显示，请检查本机服务后重试。</p>
            </div>
          ) : activeOpportunities.length === 0 ? (
            <div className="empty-card">
              <p>这里会显示你已保存的求职机会。</p>
              <button className="secondary" onClick={() => navigate("jobs")}>先看看岗位</button>
            </div>
          ) : (
            <div className="recent-list">
              {activeOpportunities.slice(0, 4).map((opportunity) => (
                <button
                  className="recent-item"
                  key={opportunity.id}
                  onClick={() => navigate("opportunities", opportunity.id)}
                >
                  <span className="recent-copy">
                    <strong>{opportunity.title}</strong>
                    <small>{opportunity.company_name}</small>
                  </span>
                  <span className={`status-pill status-${opportunity.status}`}>
                    {statusLabels[opportunity.status] ?? opportunity.status}
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="dashboard-footer-note">
        <span aria-hidden="true">i</span>
        <p>你的求职记录保存在本机。投递由你亲自完成，工作台只记录你确认发生的进展。</p>
      </section>
    </div>
  );
}

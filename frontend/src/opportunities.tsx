import React from "react";
import { ActionForm } from "./forms";
import { safeLink } from "./api";
import type { CommandApi, Prep } from "./types";
export function Preparation({
  prep,
  api,
  refresh,
}: {
  prep: Prep;
  api: CommandApi;
  refresh: () => void;
}) {
  const step = prep.next_step;
  const href = safeLink(prep.apply_url);
  return (
    <section className="preparation">
      <h3>
        {prep.job.title} · JD v{prep.job.revision}
      </h3>
      <p>
        {prep.resume
          ? `简历 v${prep.resume.revision}`
          : prep.resume_exception || "尚未选择简历"}{" "}
        · {prep.channel}
      </p>
      {prep.resume && (
        <details>
          <summary>核对固定简历正文</summary>
          <p className="raw">{prep.resume.text_content}</p>
        </details>
      )}
      <details>
        <summary>核对固定 JD 原文</summary>
        <p className="raw">{prep.job.description_text || "职责未知"}</p>
        <p className="raw">{prep.job.requirements_text || "要求未知"}</p>
      </details>
      <p className="notice">
        {prep.cooldown_snapshot.status === "present"
          ? "有冷却期，需要两次确认"
          : prep.cooldown_snapshot.status === "absent"
            ? "未发现冷却期，一次确认"
            : "冷却期待核实，一次确认即可"}
        。{prep.cooldown_snapshot.explanation}
      </p>
      {step === "relink_job" ? (
        <p role="status">请先重新关联岗位，再核对材料。</p>
      ) : step === "deferred" ? (
        <p>已暂缓，重新保存准备材料后继续。</p>
      ) : step === "manual_apply" ? (
        <div className="notice success">
          <p>材料已确认，可自行投递。完成后请在下方记录实际结果。</p>
          {href && (
            <a href={href} target="_blank" rel="noopener noreferrer">
              打开投递页面
            </a>
          )}
        </div>
      ) : (
        <ActionForm
          key={`${prep.id}-${step}-${prep.revision}`}
          id={`confirm-${prep.id}-${step}-${prep.revision}`}
          title=""
          fields={[]}
          api={api}
          command="ConfirmPreparation"
          expected={prep.revision}
          input={() => ({ preparation_id: prep.id, step })}
          submitLabel={
            step === "cooldown" ? "确认了解冷却期，仍自行投递" : "确认材料"
          }
          onSaved={refresh}
          onConflict={refresh}
        />
      )}
      {["materials", "cooldown", "manual_apply"].includes(step) && (
        <ActionForm
          id={`defer-${prep.id}-${prep.revision}`}
          title=""
          fields={[]}
          api={api}
          command="DeferPreparation"
          expected={prep.revision}
          input={() => ({ preparation_id: prep.id })}
          submitLabel="暂缓"
          onSaved={refresh}
          onConflict={refresh}
        />
      )}
    </section>
  );
}

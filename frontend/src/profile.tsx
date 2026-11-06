import React, { useState } from "react";
import { ActionForm, type Field } from "./forms";
import { useQuery } from "./query";
import type { ApiPort, MaterialVersion, Page, Profile, Values } from "./types";
export const split = (value = "") =>
  value
    .split(/[,，\n]/)
    .map((x) => x.trim())
    .filter(Boolean);
const splitLines = (value = "") =>
  value
    .split(/\r?\n/)
    .map((x) => x.trim())
    .filter(Boolean);
const targetFields: Field[] = [
  { name: "label", label: "目标名称", required: true },
  {
    name: "keywords",
    label: "岗位关键词",
    required: true,
    help: "多个关键词用逗号分隔",
  },
  {
    name: "cityMode",
    label: "城市范围",
    required: true,
    options: [
      { value: "any", label: "不限城市" },
      { value: "cities", label: "指定城市" },
    ],
  },
  {
    name: "cities",
    label: "指定城市",
    help: "指定城市时必填，多个城市用逗号分隔",
  },
  { name: "must", label: "硬条件", multiline: true, help: "每行一个明确条件" },
  { name: "prefer", label: "偏好", multiline: true },
];
const targetInput = (v: Values) => {
  const cities = v.cityMode === "cities" ? split(v.cities) : [];
  if (v.cityMode === "cities" && !cities.length)
    throw new Error("请填写至少一个指定城市");
  return {
    label: v.label,
    criteria: {
      keywords: split(v.keywords),
      cities,
      any_city: v.cityMode === "any",
      conditions: [
        ...splitLines(v.must).map((value) => ({
          field: "description",
          operator: "contains",
          value,
          importance: "must",
        })),
        ...splitLines(v.prefer).map((value) => ({
          field: "description",
          operator: "contains",
          value,
          importance: "prefer",
        })),
      ],
    },
    active: true,
  };
};
type Condition = NonNullable<
  Profile["targets"][number]["criteria"]["conditions"]
>[number];
const editableCondition = (c: Condition) =>
  c.field === "description" &&
  c.operator === "contains" &&
  typeof c.value === "string";
function conditionText(c: Condition) {
  const value = c.value;
  const text =
    value && typeof value === "object" && "amount" in value
      ? `${value.amount} ${"currency" in value ? value.currency : ""} / ${"period" in value ? value.period : ""}`
      : Array.isArray(value)
        ? value.join("、")
        : String(value);
  return `${c.importance === "must" ? "硬条件" : "偏好"} · ${c.field === "salary" ? "薪资" : c.field} ${c.operator === "gte" ? "≥" : c.operator} ${text}`;
}
const factFields: Field[] = [
  {
    name: "kind",
    label: "经历类型",
    required: true,
    options: [
      { value: "employment", label: "工作经历" },
      { value: "project", label: "项目经历" },
      { value: "skill", label: "技能" },
      { value: "education", label: "教育" },
      { value: "achievement", label: "成果" },
    ],
  },
  { name: "title", label: "经历标题", required: true },
  { name: "description", label: "经历原文", required: true, multiline: true },
];
export function ProfilePage({
  api,
  revision,
  refresh,
}: {
  api: ApiPort;
  revision: number;
  refresh: () => void;
}) {
  const { data, error, loading } = useQuery<Profile>(api, "profile", revision);
  return (
    <div className="document-page">
      <p className="intro">
        先整理方向和真实经历。保存的简历有独立版本，修改不会覆盖已用材料。
      </p>
      {error && (
        <p role="alert" className="error">
          {error.message}
        </p>
      )}
      {loading && <p role="status">正在读取资料…</p>}
      {data && (
        <>
          <section>
            <h2>求职目标</h2>
            {!data.targets.length && <p className="muted">还没有求职目标。</p>}
            {data.targets.map((target) => (
              <details key={target.id}>
                <summary>
                  {target.label} · {target.criteria.keywords.join(" / ")} ·{" "}
                  {target.criteria.any_city
                    ? "不限城市"
                    : target.criteria.cities?.join("、")}
                </summary>
                {target.criteria.conditions
                  ?.filter((c) => !editableCondition(c))
                  .map((c, i) => (
                    <p key={i} className="muted">
                      {conditionText(c)}（编辑时保留）
                    </p>
                  ))}
                <ActionForm
                  key={`${target.id}-${target.revision}`}
                  id={`target-${target.id}`}
                  title="编辑目标"
                  api={api}
                  fields={targetFields}
                  command="SaveTarget"
                  expected={target.revision}
                  initial={{
                    label: target.label,
                    keywords: target.criteria.keywords.join(", "),
                    cityMode: target.criteria.any_city ? "any" : "cities",
                    cities: target.criteria.cities?.join(", ") ?? "",
                    must:
                      target.criteria.conditions
                        ?.filter(
                          (c) =>
                            c.importance === "must" && editableCondition(c),
                        )
                        .map((c) => c.value)
                        .join("\n") ?? "",
                    prefer:
                      target.criteria.conditions
                        ?.filter(
                          (c) =>
                            c.importance === "prefer" && editableCondition(c),
                        )
                        .map((c) => c.value)
                        .join("\n") ?? "",
                  }}
                  input={(v) => {
                    const value = targetInput(v);
                    return {
                      ...value,
                      id: target.id,
                      active: target.active,
                      criteria: {
                        ...value.criteria,
                        conditions: [
                          ...(target.criteria.conditions ?? []).filter(
                            (c) => !editableCondition(c),
                          ),
                          ...value.criteria.conditions,
                        ],
                      },
                    };
                  }}
                  onSaved={refresh}
                />
              </details>
            ))}
            <ActionForm
              id="new-target"
              title="新增目标"
              fields={targetFields}
              api={api}
              command="SaveTarget"
              input={targetInput}
              onSaved={refresh}
              submitLabel="保存目标"
            />
          </section>
          <section>
            <h2>经历与事实</h2>
            <p className="muted">
              先保存草稿，核对后再确认。只有已确认事实可加入简历版本。
            </p>
            {data.facts.map((fact) => (
              <details key={fact.id}>
                <summary>
                  {fact.content.title} ·{" "}
                  {fact.status === "confirmed" ? "已确认" : "待核对"}
                </summary>
                <p className="raw">{fact.content.description}</p>
                {fact.status === "draft" && (
                  <ActionForm
                    id={`fact-confirm-${fact.id}-${fact.revision}`}
                    title=""
                    fields={[]}
                    api={api}
                    command="ConfirmFact"
                    expected={fact.revision}
                    input={() => ({ id: fact.id })}
                    onSaved={refresh}
                    onConflict={refresh}
                    submitLabel="确认事实"
                  />
                )}
                <ActionForm
                  key={`${fact.id}-${fact.revision}`}
                  id={`fact-edit-${fact.id}`}
                  title="修订经历"
                  fields={factFields}
                  initial={{
                    kind: fact.kind,
                    title: fact.content.title,
                    description: fact.content.description,
                  }}
                  api={api}
                  command="SaveFact"
                  expected={fact.revision}
                  input={(v) => ({
                    id: fact.id,
                    kind: v.kind,
                    content: {
                      ...fact.content,
                      title: v.title,
                      description: v.description,
                    },
                    provenance: { kind: "user" },
                  })}
                  onSaved={refresh}
                />
              </details>
            ))}
            <ActionForm
              id="new-fact"
              title="补充经历"
              fields={factFields}
              api={api}
              command="SaveFact"
              input={(v) => ({
                kind: v.kind,
                content: { title: v.title, description: v.description },
                provenance: { kind: "user" },
              })}
              onSaved={refresh}
              submitLabel="保存经历草稿"
            />
          </section>
          <section>
            <h2>简历与材料</h2>
            {data.materials.map((material) => (
              <Material
                key={material.id}
                material={material}
                facts={data.facts}
                api={api}
                revision={revision}
                refresh={refresh}
              />
            ))}
            <ActionForm
              id="new-resume"
              title="粘贴简历"
              fields={[
                { name: "label", label: "简历名称", required: true },
                {
                  name: "text",
                  label: "简历正文",
                  required: true,
                  multiline: true,
                },
              ]}
              api={api}
              command="ImportMaterial"
              input={(v) => v}
              onSaved={refresh}
              submitLabel="保存简历"
            />
          </section>
        </>
      )}
    </div>
  );
}
function Material({
  material,
  facts,
  api,
  revision,
  refresh,
}: {
  material: Profile["materials"][number];
  facts: Profile["facts"];
  api: ApiPort;
  revision: number;
  refresh: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details onToggle={(e) => setExpanded(e.currentTarget.open)}>
      <summary>
        {material.label} · 最新 v{material.latest_version.revision}
      </summary>
      <p className="raw">{material.latest_version.text_content}</p>
      {!!material.latest_version.fact_snapshot?.facts.length && (
        <p className="muted">
          本次修订沿用已引用的{" "}
          {material.latest_version.fact_snapshot.facts.length}{" "}
          项事实，可再补充已确认事实。
        </p>
      )}
      {expanded && <Versions api={api} id={material.id} revision={revision} />}
      <ActionForm
        key={material.latest_version.id}
        id={`resume-${material.id}`}
        title="另存一个修订"
        fields={[
          { name: "text", label: "修订正文", required: true, multiline: true },
          {
            name: "fact",
            label: "引用已确认事实（可选）",
            options: facts
              .filter((f) => f.status === "confirmed")
              .map((f) => ({ value: f.id, label: f.content.title })),
          },
        ]}
        initial={{
          text: material.latest_version.text_content,
          _parent_version_id: material.latest_version.id,
          _fact_ids: JSON.stringify(
            material.latest_version.fact_snapshot?.facts.map((f) => f.id) ?? [],
          ),
        }}
        api={api}
        command="SaveMaterialVersion"
        input={(v) => ({
          material_id: material.id,
          parent_version_id: v._parent_version_id,
          text: v.text,
          fact_ids: Array.from(
            new Set([
              ...(JSON.parse(v._fact_ids ?? "[]") as string[]),
              ...(v.fact ? [v.fact] : []),
            ]),
          ),
        })}
        onSaved={refresh}
      />
    </details>
  );
}
function Versions({
  api,
  id,
  revision,
}: {
  api: ApiPort;
  id: string;
  revision: number;
}) {
  const result = useQuery<Page<MaterialVersion>>(
    api,
    `materials/${id}/versions?limit=100`,
    revision,
  );
  return (
    <div>
      {result.error && <p role="alert">{result.error.message}</p>}
      {result.data?.items.map((version) => (
        <details key={version.id}>
          <summary>
            v{version.revision} ·{" "}
            {new Date(version.created_at).toLocaleString()}
          </summary>
          <p className="raw">{version.text_content}</p>
        </details>
      ))}
      {result.data?.next_cursor && (
        <p>仍有更早版本；准备材料选择器可读取全部修订。</p>
      )}
    </div>
  );
}

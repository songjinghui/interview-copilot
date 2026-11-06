import React, { useEffect, useRef, useState } from "react";
import { drafts, type Draft } from "./drafts";
import type { ApiError, CommandApi, Envelope, Values } from "./types";
export interface Field {
  name: string;
  label: string;
  required?: boolean;
  multiline?: boolean;
  type?: string;
  options?: { value: string; label: string }[];
  help?: string;
}
interface FormProps {
  id: string;
  title: string;
  fields: Field[];
  command: string;
  api: CommandApi;
  input: (values: Values) => Record<string, unknown>;
  initial?: Values;
  expected?: number;
  onSaved: (data: Record<string, unknown>) => void;
  onConflict?: () => void;
  submitLabel?: string;
}
export function ActionForm({
  id,
  title,
  fields,
  command,
  api,
  input,
  initial = {},
  expected,
  onSaved,
  onConflict,
  submitLabel = "保存",
}: FormProps) {
  const [draft, setDraft] = useState<Draft>({ values: initial, expected });
  const [loaded, setLoaded] = useState(false),
    [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false),
    [notice, setNotice] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  useEffect(() => {
    let active = true;
    drafts
      .get(id)
      .then((value) => {
        if (active) {
          if (value) {
            setDraft(value);
            setSaved(true);
          }
          setLoaded(true);
        }
      })
      .catch((e) => {
        if (active) setError(e);
      });
    return () => {
      active = false;
    };
  }, [id]);
  async function persist(next: Draft) {
    setDraft(next);
    setSaved(false);
    const result = queue.current.then(() => drafts.put(id, next));
    queue.current = result.catch(() => {});
    await result;
    setSaved(true);
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    setNotice("");
    let pending = draft,
      attempted = false;
    try {
      await queue.current;
      if (!pending.envelope) {
        let payload;
        try {
          payload = input(pending.values);
        } catch (e) {
          setError({ message: (e as Error).message });
          return;
        }
        const envelope: Envelope = {
          request_id: crypto.randomUUID(),
          command,
          input: payload,
          ...(pending.expected !== undefined
            ? { expected_revision: pending.expected }
            : {}),
        };
        pending = { ...pending, envelope };
      }
      await persist(pending);
      attempted = true;
      const result = await api.command(pending.envelope!);
      await drafts.remove(id);
      setDraft({ values: initial, expected });
      setSaved(false);
      setNotice("已保存");
      onSaved(result.data);
    } catch (e) {
      const failure = e as ApiError;
      if (!attempted) {
        setError({
          message: failure.message || "草稿未能保存，请保留当前页面",
        });
      } else if (
        failure.code &&
        !["SESSION_REQUIRED", "BUSY", "STORAGE_ERROR"].includes(failure.code)
      ) {
        if (failure.code === "REVISION_CONFLICT" && fields.length === 0) {
          try {
            await drafts.remove(id);
            setDraft({ values: initial, expected });
            setError({
              ...failure,
              message:
                "记录已更新，正在读取最新记录；请核对当前内容后重新确认。",
            });
            onConflict?.();
          } catch {
            setError({
              message: "确认已被拒绝，但本地请求未能清理；请刷新记录后再继续。",
            });
          }
        } else {
          await persist({ ...pending, envelope: undefined }).catch(() => {});
          setError(failure);
        }
      } else {
        setError({
          message: failure.code
            ? failure.message
            : "未能确认保存结果。草稿已保留，请重试原请求。",
        });
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="editor" onSubmit={submit} aria-label={title}>
      {title && <h3>{title}</h3>}
      {!loaded ? (
        error ? (
          <p role="alert" className="error">
            {error.message}
          </p>
        ) : (
          <p role="status">正在恢复草稿…</p>
        )
      ) : (
        <>
          <fieldset disabled={busy || !!draft.envelope}>
            {fields.map((field) => (
              <label key={field.name}>
                {field.label}
                {field.required && <span aria-hidden="true"> *</span>}
                {field.options ? (
                  <select
                    aria-label={field.label}
                    required={field.required}
                    value={draft.values[field.name] ?? ""}
                    onChange={(e) => {
                      void persist({
                        ...draft,
                        values: {
                          ...draft.values,
                          [field.name]: e.target.value,
                        },
                      }).catch(setError);
                    }}
                  >
                    <option value="">请选择</option>
                    {field.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : field.multiline ? (
                  <textarea
                    aria-label={field.label}
                    required={field.required}
                    rows={5}
                    value={draft.values[field.name] ?? ""}
                    onChange={(e) => {
                      void persist({
                        ...draft,
                        values: {
                          ...draft.values,
                          [field.name]: e.target.value,
                        },
                      }).catch(setError);
                    }}
                  />
                ) : (
                  <input
                    aria-label={field.label}
                    required={field.required}
                    type={field.type ?? "text"}
                    value={draft.values[field.name] ?? ""}
                    onChange={(e) => {
                      void persist({
                        ...draft,
                        values: {
                          ...draft.values,
                          [field.name]: e.target.value,
                        },
                      }).catch(setError);
                    }}
                  />
                )}
                {field.help && <small>{field.help}</small>}
              </label>
            ))}
          </fieldset>
          {saved && fields.length > 0 && <small>草稿已保存在此浏览器</small>}
          {error && (
            <p role="alert" className="error">
              {error.code === "REVISION_CONFLICT"
                ? "记录已在其他操作中更新。你的草稿已保留，请先核对最新记录。"
                : error.message}
            </p>
          )}
          {fields.length > 0 && error?.code === "REVISION_CONFLICT" &&
            (error.details?.revision || error.details?.parent_version_id) && (
              <button
                type="button"
                onClick={() => {
                  void persist({
                    ...draft,
                    expected: error.details?.revision ?? draft.expected,
                    values: {
                      ...draft.values,
                      ...(error.details?.parent_version_id
                        ? {
                            _parent_version_id: error.details.parent_version_id,
                          }
                        : {}),
                    },
                  })
                    .then(() => setError(null))
                    .catch(setError);
                }}
              >
                我已核对当前记录，保留草稿继续保存
              </button>
            )}
          <div className="actions">
            <button type="submit" disabled={busy}>
              {busy ? "正在保存…" : draft.envelope ? "重试保存" : submitLabel}
            </button>
            {fields.length > 0 && !draft.envelope && (
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  void queue.current
                    .then(() => drafts.remove(id))
                    .then(() => {
                      setDraft({ values: initial, expected });
                      setSaved(false);
                      setError(null);
                    });
                }}
              >
                放弃草稿
              </button>
            )}
          </div>
          {notice && (
            <p role="status" className="success">
              {notice}
            </p>
          )}
        </>
      )}
    </form>
  );
}

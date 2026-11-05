import type { Envelope, Values } from "./types";
export interface Draft {
  values: Values;
  envelope?: Envelope;
  expected?: number;
}
let workspace = "unconnected";
export function useWorkspace(id: string) {
  workspace = id;
}
async function database() {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open("interview-copilot-drafts-" + workspace, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("drafts");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () =>
      reject(new Error("浏览器无法保存草稿，请检查存储权限"));
  });
}
async function operation<T>(
  mode: IDBTransactionMode,
  action: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction("drafts", mode);
    const request = action(transaction.objectStore("drafts"));
    transaction.oncomplete = () => {
      db.close();
      resolve(request.result);
    };
    transaction.onerror = transaction.onabort = () => {
      db.close();
      reject(new Error("草稿未能保存，请保留当前页面"));
    };
  });
}
export const drafts = {
  get: (id: string) =>
    operation<Draft | undefined>("readonly", (store) => store.get(id)),
  put: (id: string, draft: Draft) =>
    operation("readwrite", (store) => store.put(draft, id)),
  remove: (id: string) => operation("readwrite", (store) => store.delete(id)),
};

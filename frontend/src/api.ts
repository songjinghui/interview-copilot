import { useWorkspace } from "./drafts";
import type { ApiPort, Envelope } from "./types";
export class Api implements ApiPort {
  private token = "";
  private renewed = 0;
  constructor(private fetcher: typeof fetch = fetch.bind(window)) {}
  private async request(path: string, method = "GET", body?: unknown) {
    const response = await this.fetcher(path, {
      method,
      headers: {
        ...(this.token ? { Authorization: "Bearer " + this.token } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const result = await response.json();
    if (!response.ok)
      throw result.error ?? { code: "HTTP_ERROR", message: "本地服务暂不可用" };
    return result;
  }
  async connect() {
    const fragment = new URLSearchParams(location.hash.slice(1));
    const nonce = fragment.get("bootstrap");
    if (nonce)
      history.replaceState(null, "", location.pathname + location.search);
    this.token = sessionStorage.getItem("interview-session") ?? "";
    const result = nonce
      ? await this.request("/session/exchange", "POST", { nonce })
      : await this.request("/session/renew", "POST", {});
    this.token = result.token;
    sessionStorage.setItem("interview-session", this.token);
    if (result.workspace) useWorkspace(result.workspace);
    this.renewed = Date.now();
  }
  private async renewIfNeeded() {
    if (Date.now() - this.renewed < 5 * 60 * 1000) return;
    const result = await this.request("/session/renew", "POST", {});
    this.token = result.token;
    sessionStorage.setItem("interview-session", this.token);
    this.renewed = Date.now();
  }
  async query<T>(path: string): Promise<T> {
    await this.renewIfNeeded();
    return this.request("/api/v1/" + path);
  }
  async command(envelope: Envelope) {
    await this.renewIfNeeded();
    return this.request("/api/v1/commands", "POST", envelope);
  }
}
export function safeLink(value?: string | null) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

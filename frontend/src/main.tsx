import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Api } from "./api";
import { App } from "./App";
import "./style.css";
const api = new Api();
function Start() {
  const [ready, setReady] = useState(false),
    [error, setError] = useState("");
  const connect = () => {
    setError("");
    api
      .connect()
      .then(() => setReady(true))
      .catch((e) =>
        setError(
          e.message || "无法连接本地服务，请从启动入口重新打开求职助手。",
        ),
      );
  };
  useEffect(connect, []);
  return ready ? (
    <App api={api} />
  ) : (
    <main className="welcome">
      <p className="eyebrow">求职助手 · 本机工作台</p>
      <h1>整理方向，接着向前</h1>
      {error ? (
        <>
          <p role="alert">{error}</p>
          <p>如果会话已过期，请从启动入口重新打开求职助手。</p>
          <button onClick={connect}>重新连接</button>
        </>
      ) : (
        <p role="status">正在连接你的本地资料…</p>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Start />);

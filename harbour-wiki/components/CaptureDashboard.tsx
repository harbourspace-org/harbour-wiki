"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

type Agent = {
  agent_id: string;
  hostname: string;
  scheduler_status: string;
  session_id: string | null;
  current_course_name: string | null;
  current_lecture: number | null;
  current_slot: number | null;
  current_started_at: string | null;
  current_ends_at: string | null;
  next_course_name: string | null;
  next_lecture: number | null;
  next_slot: number | null;
  next_starts_at: string | null;
  next_ends_at: string | null;
  audio_status: string;
  camera_status: string;
  zoom_status: string;
  outbox_pending: number;
  errors: string[];
  updated_at: string;
  last_event_at: string;
};

type Command = {
  id: number;
  agentId: string;
  kind: "stop" | "extend" | "skip";
  status: "pending" | "acknowledged" | "failed";
  createdAt: string;
  result: string | null;
  error: string | null;
};

type DashboardData = {
  agents: Agent[];
  commands: Command[];
  serverTime: string;
};

const GOOD = new Set(["recording", "prewarming", "running", "connected", "idle"]);

function when(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function Status({ label, value }: { label: string; value: string }) {
  const tone = GOOD.has(value) ? "good" : value === "stopped" || value === "disabled" ? "quiet" : "warn";
  return (
    <div className="capture-status">
      <span className={`capture-dot ${tone}`} aria-hidden="true" />
      <span>
        <b>{label}</b>
        <small>{value}</small>
      </span>
    </div>
  );
}

export function CaptureDashboard() {
  const [key, setKey] = useState("");
  const [draftKey, setDraftKey] = useState("");
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    const saved = sessionStorage.getItem("capture-dashboard-key") ?? "";
    setKey(saved);
    setDraftKey(saved);
  }, []);

  const refresh = useCallback(async () => {
    if (!key) return;
    try {
      const response = await fetch(`/api/capture/control?key=${encodeURIComponent(key)}`, {
        cache: "no-store",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setData(body);
      setError("");
    } catch (cause) {
      setError(String(cause));
    }
  }, [key]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  function unlock(event: FormEvent) {
    event.preventDefault();
    const clean = draftKey.trim();
    sessionStorage.setItem("capture-dashboard-key", clean);
    setKey(clean);
  }

  async function command(agentId: string, kind: Command["kind"]) {
    if ((kind === "stop" || kind === "skip") && !window.confirm(
      kind === "stop" ? "Stop the current lecture now?" : "Skip the next scheduled lecture?",
    )) return;
    setBusy(`${agentId}:${kind}`);
    try {
      const response = await fetch("/api/capture/control", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ key, agentId, kind, minutes: kind === "extend" ? 15 : undefined }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setError("");
      await refresh();
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy("");
    }
  }

  if (!key) {
    return (
      <main className="shell">
        <header className="masthead">
          <Link className="wordmark" href="/">Harbour<b>.</b>Wiki</Link>
          <span className="meta">capture control</span>
        </header>
        <h1>Capture control</h1>
        <form className="capture-login panel" onSubmit={unlock}>
          <label className="label" htmlFor="operator-key">Operator key</label>
          <div className="capture-login-row">
            <input
              id="operator-key"
              className="field"
              type="password"
              value={draftKey}
              onChange={(event) => setDraftKey(event.target.value)}
              autoComplete="current-password"
              required
            />
            <button className="btn" type="submit">Open panel</button>
          </div>
        </form>
      </main>
    );
  }

  return (
    <main className="shell capture-shell">
      <header className="masthead">
        <Link className="wordmark" href="/">Harbour<b>.</b>Wiki</Link>
        <span className="meta">capture control · refreshes every 5 seconds</span>
      </header>
      <div className="capture-heading">
        <div>
          <h1>Capture control</h1>
          <p className="subtitle">Remote status and safe controls for classroom recorders.</p>
        </div>
        <button className="btn" onClick={() => {
          sessionStorage.removeItem("capture-dashboard-key");
          setKey("");
          setData(null);
        }}>Lock</button>
      </div>

      {error && <div className="capture-alert"><b>Panel error:</b> {error}</div>}
      {!data && !error && <p className="muted">Loading recorder status…</p>}
      {data?.agents.length === 0 && <div className="panel">No capture agent has checked in yet.</div>}

      {data?.agents.map((agent) => {
        const serverNow = new Date(data.serverTime).getTime();
        const staleFor = Math.max(0, serverNow - new Date(agent.updated_at).getTime());
        const online = staleFor < 20_000;
        const agentCommands = data.commands.filter((item) => item.agentId === agent.agent_id).slice(0, 5);
        return (
          <section className="capture-card" key={agent.agent_id}>
            <div className="capture-card-head">
              <div>
                <span className={`capture-online ${online ? "online" : "offline"}`}>
                  {online ? "Online" : "Offline"}
                </span>
                <h2>{agent.hostname}</h2>
                <small className="muted">{agent.agent_id}</small>
              </div>
              <Status label="Scheduler" value={online ? agent.scheduler_status : "offline"} />
            </div>

            <div className="capture-course-grid">
              <article>
                <span className="capture-eyebrow">Current lecture</span>
                {agent.current_course_name ? (
                  <>
                    <strong>{agent.current_course_name}</strong>
                    <span>Lecture {agent.current_lecture} · slot {agent.current_slot}</span>
                    <small>{when(agent.current_started_at)} – {when(agent.current_ends_at)}</small>
                  </>
                ) : <strong>Nothing recording</strong>}
              </article>
              <article>
                <span className="capture-eyebrow">Next slot</span>
                {agent.next_course_name ? (
                  <>
                    <strong>{agent.next_course_name}</strong>
                    <span>Lecture {agent.next_lecture} · slot {agent.next_slot}</span>
                    <small>{when(agent.next_starts_at)}</small>
                  </>
                ) : <strong>Schedule complete</strong>}
              </article>
            </div>

            <div className="capture-status-grid">
              <Status label="Audio" value={online ? agent.audio_status : "offline"} />
              <Status label="Camera" value={online ? agent.camera_status : "offline"} />
              <Status label="Zoom" value={online ? agent.zoom_status : "offline"} />
            </div>

            <dl className="capture-facts">
              <div><dt>Last heartbeat</dt><dd>{when(agent.updated_at)}</dd></div>
              <div><dt>Last lecture event</dt><dd>{when(agent.last_event_at)}</dd></div>
              <div><dt>Outbox</dt><dd className={agent.outbox_pending > 0 ? "capture-warning" : ""}>{agent.outbox_pending} pending</dd></div>
            </dl>

            {agent.errors?.length > 0 && (
              <div className="capture-errors">
                <b>Errors</b>
                <ul>{agent.errors.map((item, index) => <li key={`${index}:${item}`}>{item}</li>)}</ul>
              </div>
            )}

            <div className="capture-actions">
              <button
                className="btn capture-danger"
                disabled={!online || !agent.current_course_name || Boolean(busy)}
                onClick={() => void command(agent.agent_id, "stop")}
              >Stop</button>
              <button
                className="btn"
                disabled={!online || !agent.current_course_name || Boolean(busy)}
                onClick={() => void command(agent.agent_id, "extend")}
              >Extend +15 min</button>
              <button
                className="btn"
                disabled={!online || !agent.next_course_name || Boolean(busy)}
                onClick={() => void command(agent.agent_id, "skip")}
              >Skip next</button>
              {busy.startsWith(`${agent.agent_id}:`) && <span className="muted">Queueing…</span>}
            </div>

            {agentCommands.length > 0 && (
              <details className="capture-commands">
                <summary>Recent commands</summary>
                <ul>
                  {agentCommands.map((item) => (
                    <li key={item.id}>
                      <b>{item.kind}</b> · {item.status} · {when(item.createdAt)}
                      {(item.error || item.result) && <> — {item.error ?? item.result}</>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>
        );
      })}
    </main>
  );
}

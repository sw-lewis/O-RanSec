import { useEffect, useRef, useState } from "react";
import type { State } from "./types";

export async function get<T = unknown>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 300)}`);
  return r.json();
}

function wsUrl(path: string) {
  return `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${path}`;
}

/** Live testbed state pushed by the backend every ~2 s; reconnects on its own. */
export function useLiveState() {
  const [state, setState] = useState<State | null>(null);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;
    const open = () => {
      ws = new WebSocket(wsUrl("/ws/state"));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => setState(JSON.parse(e.data));
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(open, 2000);
      };
    };
    open();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, []);
  return { state, connected };
}

/** Polls an endpoint while mounted. */
export function usePoll<T>(path: string | null, ms = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const tick = useRef(0);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    const run = async () => {
      const my = ++tick.current;
      setLoading(true);
      try {
        const d = await get<T>(path);
        if (alive && my === tick.current) { setData(d); setError(null); }
      } catch (e) {
        if (alive) setError(String(e));
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    const t = window.setInterval(run, ms);
    return () => { alive = false; clearInterval(t); };
  }, [path, ms, nonce]);
  return { data, error, loading, refresh: () => setNonce((n) => n + 1) };
}

export function openSocket(path: string, onMessage: (data: unknown) => void, onState?: (open: boolean) => void) {
  const ws = new WebSocket(wsUrl(path));
  ws.onopen = () => onState?.(true);
  ws.onclose = () => onState?.(false);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  return ws;
}

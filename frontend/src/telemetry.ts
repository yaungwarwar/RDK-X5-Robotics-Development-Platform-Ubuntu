import { useEffect, useState } from "react";
import type { Snapshot } from "./types";
export function useTelemetry() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<(Snapshot | null)[]>([]);
  const [connected, setConnected] = useState(false);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    let stopped = false,
      socket: WebSocket | undefined,
      retry: ReturnType<typeof setTimeout> | undefined,
      watchdog: ReturnType<typeof setTimeout> | undefined,
      attempt = 0;
    let lastSequence = -1,
      lastTimestamp = "";
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/v1/telemetry`,
      );
      const resetWatchdog = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => socket?.close(), 10000);
      };
      socket.onopen = () => {
        setConnected(true);
        resetWatchdog();
      };
      socket.onmessage = (event) => {
        try {
          const next = JSON.parse(event.data) as Snapshot;
          if (
            !next.data ||
            !next.timestamp ||
            !["mock", "native"].includes(next.mode) ||
            !Number.isInteger(next.sequence)
          )
            return;
          attempt = 0;
          resetWatchdog();
          setSnapshot(next);
          if (
            next.sequence !== lastSequence ||
            next.timestamp !== lastTimestamp
          ) {
            const elapsed = lastTimestamp
              ? Date.parse(next.timestamp) - Date.parse(lastTimestamp)
              : 0;
            const missed =
              lastTimestamp !== "" &&
              (next.sequence > lastSequence + 1 ||
                elapsed > Math.max(2500, next.interval_seconds * 2500));
            setHistory((h) =>
              [...h, ...(missed ? [null] : []), next].slice(-60),
            );
            lastSequence = next.sequence;
            lastTimestamp = next.timestamp;
          }
        } catch {
          socket?.close();
        }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        clearTimeout(watchdog);
        setConnected(false);
        if (!stopped)
          retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10000));
      };
    };
    connect();
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearTimeout(watchdog);
      clearInterval(timer);
      socket?.close();
    };
  }, []);
  const age = snapshot
    ? Math.max(0, (clock - Date.parse(snapshot.timestamp)) / 1000)
    : Infinity;
  return {
    snapshot,
    history,
    connected,
    age,
    stale: !!snapshot && (snapshot.stale || age > snapshot.stale_after_seconds),
  };
}

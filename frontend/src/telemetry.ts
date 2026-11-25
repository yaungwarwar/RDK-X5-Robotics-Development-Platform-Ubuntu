import { useEffect, useState } from "react";
import type { Snapshot } from "./types";

// Reject incomplete data at the transport boundary rather than inventing readings.
function completeSnapshot(value: unknown): value is Snapshot {
  if (!value || typeof value !== "object") return false;
  const x = value as Snapshot; // Every accessed member is checked before acceptance.
  const object = (v: unknown): v is Record<string, unknown> =>
    !!v && typeof v === "object" && !Array.isArray(v);
  const metric = (v: unknown) =>
    object(v) &&
    "value" in v &&
    typeof v.source === "string" &&
    typeof v.status === "string" &&
    typeof v.age_seconds === "number" &&
    typeof v.stale === "boolean";
  const fields = (v: unknown, names: string[]) =>
    object(v) && names.every((name) => metric(v[name]));
  const frequency = (v: unknown) =>
    fields(v, [
      "current",
      "min",
      "max",
      "governor",
      "available_frequencies",
      "available_governors",
    ]);
  const d = x.data;
  return (
    ["mock", "native"].includes(x.mode) &&
    typeof x.timestamp === "string" &&
    Number.isFinite(Date.parse(x.timestamp)) &&
    Number.isInteger(x.sequence) &&
    typeof x.interval_seconds === "number" &&
    typeof x.stale_after_seconds === "number" &&
    object(d) &&
    fields(d.system, ["hostname", "os", "kernel", "architecture", "uptime"]) &&
    fields(d.cpu, ["overall", "core_ids", "load_average"]) &&
    Array.isArray(d.cpu.cores) &&
    d.cpu.cores.every(metric) &&
    Array.isArray(d.cpu.frequencies) &&
    d.cpu.frequencies.every(metric) &&
    fields(d.memory, ["total", "used", "available", "percent"]) &&
    object(d.storage) &&
    Array.isArray(d.storage.volumes) &&
    d.storage.volumes.every(
      (v) =>
        fields(v, ["total", "used", "free", "percent"]) &&
        typeof v.path === "string",
    ) &&
    fields(d.thermal, ["cpu", "ddr", "cooling_devices"]) &&
    fields(d.bpu, [
      "devices",
      "utilization",
      "temperature",
      "cpu_temperature_proxy",
      "temperature_fallback",
    ]) &&
    frequency(d.bpu.frequency) &&
    object(d.frequencies) &&
    frequency(d.frequencies.gpu) &&
    frequency(d.frequencies.ddr) &&
    object(d.network) &&
    Array.isArray(d.network.interfaces) &&
    d.network.interfaces.every(
      (v) =>
        typeof v?.name === "string" &&
        fields(v, ["up", "addresses", "rx", "tx"]),
    ) &&
    fields(d.services, ["docker", "containerd"]) &&
    fields(d.ros2, [
      "available",
      "probe_duration",
      "last_success",
      "consecutive_failures",
      "diagnostic",
      "detail",
      "nodes",
      "topics",
    ]) &&
    object(d.cameras) &&
    metric(d.cameras.node_present) &&
    metric(d.cameras.capture) &&
    Array.isArray(d.cameras.topics) &&
    d.cameras.topics.every(
      (v) => typeof v?.name === "string" && metric(v.publishers),
    )
  );
}
export function useTelemetry() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<(Snapshot | null)[]>([]);
  const [connected, setConnected] = useState(false);
  const [invalid, setInvalid] = useState(false);
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
          const next: unknown = JSON.parse(event.data);
          if (!completeSnapshot(next)) {
            setInvalid(true);
            return;
          }
          setInvalid(false);
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
    invalid,
    age,
    stale: !!snapshot && (snapshot.stale || age > snapshot.stale_after_seconds),
  };
}

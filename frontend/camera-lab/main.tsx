import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, Camera, CircleStop, Play, ShieldCheck } from "lucide-react";
import "./style.css";

type Source = "synthetic" | "native";
type View = "left" | "right" | "combined";
type Frame = {
  sequence: number;
  view: View;
  encoding: string;
  width: number;
  height: number;
  fps: number | null;
  bandwidth_bps: number | null;
  dropped: number;
  frame_age_ms: number;
  mime?: string;
  display_mode?: string;
  source?: Source;
  calibration: Record<
    string,
    {
      width: number;
      height: number;
      model: string;
      k: number[];
      d: number[];
      calibrated: boolean;
    }
  > | null;
  worker_rss_kib?: number | null;
  worker_cpu_pct?: number | null;
  worker_dropped?: number | null;
  invalid_frames?: number | null;
  lab_peak_rss_kib?: number;
  lab_cpu_pct?: number | null;
};
function App() {
  const [view, setView] = useState<View>("left");
  const [source, setSource] = useState<Source>("synthetic");
  const [imageFormat, setImageFormat] = useState<"raw" | "compressed">("raw");
  const [running, setRunning] = useState(false);
  const [state, setState] = useState("Inactive");
  const [frame, setFrame] = useState<Frame | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [clock, setClock] = useState(Date.now());
  const [received, setReceived] = useState(0);
  const socket = useRef<WebSocket | null>(null);
  const requested = useRef(false);
  const currentUrl = useRef<string | null>(null);
  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);
  const closing = useRef<Promise<void>>(Promise.resolve());
  useEffect(() => {
    if (!running) {
      setFrame(null);
      setUrl(null);
      return;
    }
    let disposed = false;
    let ws: WebSocket | null = null;
    let meta: Frame | null = null;
    setState("Connecting");
    setFrame(null);
    setUrl(null);
    void closing.current
      .then(() => new Promise<void>((resolve) => setTimeout(resolve, 300)))
      .then(() => {
        if (disposed || !requested.current) return;
        ws = new WebSocket(
          `ws://${location.host}/lab/preview/${view}?source=${source}&image_format=${imageFormat}`,
        );
        const current = ws;
        current.binaryType = "blob";
        socket.current = current;
        current.onopen = () => {
          if (!disposed) setState("Waiting for frames");
        };
        current.onmessage = (event) => {
          if (disposed || !requested.current) return;
          if (typeof event.data === "string") {
            try {
              const message = JSON.parse(event.data);
              if (message.type === "status") setState(message.message);
              else if (message.type === "error")
                setState(`Error: ${message.message}`);
              else if (message.type === "frame") meta = message as Frame;
              else current.close();
            } catch {
              current.close();
            }
          } else if (meta && event.data instanceof Blob) {
            const next = meta;
            meta = null;
            const nextUrl = URL.createObjectURL(
              new Blob([event.data], {
                type:
                  next.mime ||
                  (source === "synthetic"
                    ? "image/svg+xml"
                    : "application/octet-stream"),
              }),
            );
            const image = new Image();
            image.onload = () => {
              if (
                disposed ||
                !requested.current ||
                current.readyState !== WebSocket.OPEN
              ) {
                URL.revokeObjectURL(nextUrl);
                return;
              }
              if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
              currentUrl.current = nextUrl;
              setUrl(nextUrl);
              setFrame(next);
              setReceived(Date.now());
              setState(
                source === "synthetic"
                  ? "Synthetic source active"
                  : "Native source active",
              );
              current.send(`ack:${next.sequence}`);
            };
            image.onerror = () => {
              URL.revokeObjectURL(nextUrl);
              setState("Error: image decoding failed");
              current.close();
            };
            image.src = nextUrl;
          }
        };
        current.onerror = () => current.close();
        current.onclose = () => {
          if (!disposed && requested.current) {
            requested.current = false;
            setState((previous) =>
              previous.startsWith("Error:") ? previous : "Disconnected",
            );
            setRunning(false);
          }
        };
      });
    return () => {
      disposed = true;
      if (ws && ws.readyState !== WebSocket.CLOSED) {
        const old = ws;
        closing.current = new Promise((resolve) => {
          const timer = setTimeout(resolve, 2500);
          old.addEventListener(
            "close",
            () => {
              clearTimeout(timer);
              resolve();
            },
            { once: true },
          );
          old.close();
        });
      }
      socket.current = null;
      if (currentUrl.current) URL.revokeObjectURL(currentUrl.current);
      currentUrl.current = null;
    };
  }, [running, view, source, imageFormat]);
  const age = frame ? (clock - received + frame.frame_age_ms) / 1000 : null;
  const stale = age !== null && age > 2;
  const display = (value: string | number | null | undefined) =>
    value == null ? "Unavailable" : value;
  return (
    <div className="shell">
      <aside className="rail">
        <div className="brand">
          <span className="brandmark">
            <Activity size={23} />
          </span>
          <div>
            <strong>
              RDK <small>CONTROL CENTER</small>
            </strong>
            <p>ROBOTICS PLATFORM</p>
          </div>
        </div>
        <div className="rail-label">LABORATORY</div>
        <div className="nav-active">
          <Camera size={18} /> Camera preview
        </div>
        <div className="rail-foot">
          <ShieldCheck size={16} /> Loopback development only
        </div>
      </aside>
      <main>
        <header>
          <div>
            <div className="eyebrow">V0.2.0 / PHASE B</div>
            <h1>Camera preview</h1>
            <p className="intro">
              Stationary bench preview with explicit source selection.
            </p>
          </div>
          <span className="mock">
            ● &nbsp; {source === "synthetic" ? "MOCK DATA" : "NATIVE BENCH"}
          </span>
        </header>
        <div className="notice">
          <strong>Laboratory prototype</strong>
          <span>
            {source === "synthetic"
              ? "These are generated frames, not a live camera. No ROS2 subscription or capture process is started."
              : "Native preview subscribes only after Start. Use only on an approved stationary bench; no capture process is launched."}
          </span>
        </div>
        <div className="viewbar" role="group" aria-label="Preview source">
          <button
            disabled={running}
            className={source === "synthetic" ? "selected" : ""}
            onClick={() => {
              setSource("synthetic");
              setState("Inactive");
            }}
          >
            Synthetic
          </button>
          <button
            disabled={running}
            className={source === "native" ? "selected" : ""}
            onClick={() => {
              setSource("native");
              setState("Inactive");
            }}
          >
            Native ROS2
          </button>
          {source === "native" && view === "combined" && (
            <select
              aria-label="Native image format"
              disabled={running}
              value={imageFormat}
              onChange={(e) =>
                setImageFormat(e.target.value as "raw" | "compressed")
              }
            >
              <option value="raw">Raw image</option>
              <option value="compressed">Compressed image</option>
            </select>
          )}
        </div>
        <div className="layout">
          <section className="panel preview">
            <div className="panel-title">
              <div>
                <span className="icon">
                  <Camera size={18} />
                </span>
                <strong>Stereo viewer</strong>
              </div>
              <span className={running && !stale ? "pill on" : "pill"}>
                <i /> {stale ? "Stale frame" : state}
              </span>
            </div>
            <div className="viewbar" role="group" aria-label="Camera view">
              {(["left", "right", "combined"] as View[]).map((v) => (
                <button
                  key={v}
                  className={v === view ? "selected" : ""}
                  aria-pressed={v === view}
                  onClick={() => {
                    setFrame(null);
                    setUrl(null);
                    if (v !== "combined") setImageFormat("raw");
                    setView(v);
                  }}
                >
                  {v === "combined"
                    ? "Combined stereo"
                    : `${v[0].toUpperCase()}${v.slice(1)} camera`}
                </button>
              ))}
            </div>
            <div className="canvas">
              {url && running && frame?.view === view ? (
                <img
                  src={url}
                  alt={`${source === "synthetic" ? "Synthetic" : "Native"} ${view} camera preview`}
                />
              ) : (
                <div className="empty">
                  <Camera size={32} />
                  <strong>
                    {state === "Disconnected" || state.startsWith("Error:")
                      ? "Preview disconnected"
                      : "Preview is inactive"}
                  </strong>
                  <span>
                    {state.startsWith("Error:")
                      ? state
                      : "Start a preview to inspect the viewer."}
                  </span>
                </div>
              )}
              <span className="overlay">
                {running
                  ? source === "synthetic"
                    ? "SYNTHETIC · NO CAMERA"
                    : "NATIVE · BENCH ONLY"
                  : "NO STREAM"}
              </span>
            </div>
            <div className="controls">
              <div>
                <strong>
                  {view === "combined"
                    ? "Combined stereo"
                    : `${view[0].toUpperCase()}${view.slice(1)} camera`}
                </strong>
                <p>
                  {source === "synthetic"
                    ? "Local synthetic source"
                    : "Native ROS2 source"}{" "}
                  · No recording
                </p>
              </div>
              <button
                className={running ? "stop" : "start"}
                onClick={() => {
                  requested.current = !running;
                  if (running) setState("Inactive");
                  setRunning(!running);
                }}
              >
                {running ? (
                  <>
                    <CircleStop size={16} /> Stop preview
                  </>
                ) : (
                  <>
                    <Play size={16} /> Start preview
                  </>
                )}
              </button>
            </div>
          </section>
          <aside className="details">
            <section className="panel">
              <div className="panel-title">
                <strong>Stream details</strong>
                <span className="muted">LIVE SESSION</span>
              </div>
              <dl>
                <div>
                  <dt>Camera availability</dt>
                  <dd>
                    {source === "synthetic"
                      ? "Unavailable · mock source"
                      : frame
                        ? "Frame received"
                        : "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Resolution</dt>
                  <dd>
                    {frame ? `${frame.width} × ${frame.height}` : "Unavailable"}
                  </dd>
                </div>
                <div>
                  <dt>Encoding</dt>
                  <dd>{display(frame?.encoding)}</dd>
                </div>
                <div>
                  <dt>Preview rendering</dt>
                  <dd>{display(frame?.display_mode)}</dd>
                </div>
                <div>
                  <dt>Measured FPS</dt>
                  <dd>
                    {frame?.fps == null ? "Unavailable" : `${frame.fps} fps`}
                  </dd>
                </div>
                <div>
                  <dt>Frame age</dt>
                  <dd>
                    {age == null
                      ? "Unavailable"
                      : `${Math.max(age, 0).toFixed(1)} s${stale ? " · STALE" : ""}`}
                  </dd>
                </div>
                <div>
                  <dt>Bandwidth</dt>
                  <dd>
                    {frame?.bandwidth_bps == null
                      ? "Unavailable"
                      : `${(frame.bandwidth_bps / 1024).toFixed(1)} KiB/s`}
                  </dd>
                </div>
                <div>
                  <dt>Dropped frames</dt>
                  <dd>{display(frame?.dropped)}</dd>
                </div>
                <div>
                  <dt>Calibration</dt>
                  <dd>
                    {frame?.calibration && Object.keys(frame.calibration).length
                      ? Object.entries(frame.calibration).map(
                          ([topic, info]) => (
                            <span key={topic}>
                              {topic}:{" "}
                              {info.calibrated ? "calibrated" : "uncalibrated"},{" "}
                              {info.width} × {info.height},{" "}
                              {info.model || "model unavailable"}, K:{" "}
                              {info.k.join(", ")}, D: {info.d.join(", ")}
                              <br />
                            </span>
                          ),
                        )
                      : "Unavailable"}
                  </dd>
                </div>
                {source === "native" && (
                  <>
                    <div>
                      <dt>Worker dropped</dt>
                      <dd>{display(frame?.worker_dropped)}</dd>
                    </div>
                    <div>
                      <dt>Invalid frames</dt>
                      <dd>{display(frame?.invalid_frames)}</dd>
                    </div>
                    <div>
                      <dt>Worker RSS</dt>
                      <dd>
                        {frame?.worker_rss_kib == null
                          ? "Unavailable"
                          : `${(frame.worker_rss_kib / 1024).toFixed(1)} MiB`}
                      </dd>
                    </div>
                    <div>
                      <dt>Worker CPU</dt>
                      <dd>
                        {frame?.worker_cpu_pct == null
                          ? "Unavailable"
                          : `${frame.worker_cpu_pct.toFixed(1)}% of one core`}
                      </dd>
                    </div>
                  </>
                )}
                <div>
                  <dt>Lab peak RSS</dt>
                  <dd>
                    {frame?.lab_peak_rss_kib == null
                      ? "Unavailable"
                      : `${(frame.lab_peak_rss_kib / 1024).toFixed(1)} MiB`}
                  </dd>
                </div>
                <div>
                  <dt>Lab CPU</dt>
                  <dd>
                    {frame?.lab_cpu_pct == null
                      ? "Unavailable"
                      : `${frame.lab_cpu_pct.toFixed(1)}% of one core`}
                  </dd>
                </div>
              </dl>
            </section>
            <section className="panel boundaries">
              <h2>Preview boundaries</h2>
              <p>
                One latest frame per viewer. Slow clients drop obsolete frames;
                stopping or leaving releases the source.
              </p>
              <div>
                ● &nbsp;{" "}
                {source === "synthetic"
                  ? "No physical camera access"
                  : "Read-only existing topics"}
              </div>
              <div>● &nbsp; No persistent image storage</div>
            </section>
          </aside>
        </div>
        <footer>
          RDK Control Center <span>·</span> Camera laboratory <span>·</span>{" "}
          {source === "synthetic"
            ? "Synthetic data only"
            : "Native bench preview"}
        </footer>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);

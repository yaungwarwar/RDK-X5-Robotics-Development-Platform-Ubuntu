import { version as releaseVersion } from "../package.json";
import {
  Component,
  StrictMode,
  useState,
  type ErrorInfo,
  type ReactNode,
} from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  ArrowDownLeft,
  ArrowUpRight,
  Box,
  Camera,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Code2,
  Cpu,
  ExternalLink,
  FileText,
  Gauge,
  HardDrive,
  Layers,
  Menu,
  Network,
  Radio,
  Server,
  ShieldCheck,
  Thermometer,
  Wifi,
  X,
  Zap,
} from "lucide-react";
import type { Metric, Snapshot } from "./types";
import { useTelemetry } from "./telemetry";
import "./style.css";
const pages = [
  ["Overview", Gauge],
  ["Hardware", Cpu],
  ["Cameras", Camera],
  ["BPU", Zap],
  ["ROS2", Network],
  ["Network", Wifi],
  ["Containers", Box],
  ["Diagnostics", FileText],
  ["About", CircleHelp],
] as const;
const subtitles: Record<string, string> = {
  Overview: "A live view of your robotics platform.",
  Hardware: "Compute, memory and thermal interfaces.",
  Cameras: "Stereo camera discovery without image subscriptions.",
  BPU: "Native accelerator interfaces and availability.",
  ROS2: "Read-only discovery of the native ROS2 graph.",
  Network: "Interface state and measured traffic.",
  Containers: "Host runtime service health.",
  Diagnostics: "Measurement availability, sources and freshness.",
  About: "Independent robotics infrastructure, built for RDK X5.",
};
function fmt(v: unknown, digits = 1): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number")
    return v.toLocaleString(undefined, { maximumFractionDigits: digits });
  if (Array.isArray(v))
    return v
      .map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x)))
      .join(", ");
  return String(v);
}
function bytes(v: number | null | undefined) {
  if (v == null) return "—";
  const i = v >= 2 ** 30 ? 3 : v >= 2 ** 20 ? 2 : v >= 1024 ? 1 : 0;
  return `${(v / 1024 ** i).toFixed(i ? 1 : 0)} ${["B", "KiB", "MiB", "GiB"][i]}`;
}
function Reading({
  m,
  digits = 1,
}: {
  m: Metric | undefined;
  digits?: number;
}) {
  return (
    <span
      title={
        m
          ? `${m.source} · ${m.reason || m.status} · ${m.age_seconds.toFixed(1)}s old`
          : "Waiting for telemetry"
      }
      className={m?.stale ? "amber" : ""}
    >
      {m?.stale && <small>STALE </small>}
      {m?.value == null ? (
        <small className="missing-value">Unavailable</small>
      ) : (
        fmt(m.value, digits)
      )}
    </span>
  );
}
function Status({
  ok,
  label,
}: {
  ok: boolean | null | undefined;
  label?: string;
}) {
  return (
    <span
      className={`status ${label === "failed" ? "bad" : ok === true ? "good" : ok === false ? "warn" : "muted"}`}
    >
      <i />
      {label ||
        (ok === true
          ? "Available"
          : ok === false
            ? "Not detected"
            : "Unavailable")}
    </span>
  );
}
function Panel({
  title,
  icon,
  aside,
  children,
  className = "",
}: {
  title: string;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <h2>
          {icon}
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}
function Chart({
  values,
  color = "#45c8f3",
  max = 100,
  label,
}: {
  values: (number | null)[];
  color?: string;
  max?: number;
  label: string;
}) {
  const width = 600,
    height = 100;
  const points = values.map((v, i) =>
    v === null
      ? null
      : `${width * (i / Math.max(values.length - 1, 1))},${height - 5 - Math.min(v / max, 1) * (height - 12)}`,
  );
  let path = "";
  let pen = false;
  points.forEach((p) => {
    if (p) {
      path += `${pen ? "L" : "M"}${p} `;
      pen = true;
    } else pen = false;
  });
  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
      >
        {[15, 50, 85].map((y) => (
          <line
            key={y}
            x1="0"
            y1={y}
            x2={width}
            y2={y}
            stroke="#243040"
            strokeDasharray="3 5"
          />
        ))}
        {points.map((point, index) =>
          point && !points[index - 1] && !points[index + 1] ? (
            <circle
              key={index}
              cx={width * (index / Math.max(values.length - 1, 1))}
              cy={
                height -
                5 -
                Math.min((values[index] ?? 0) / max, 1) * (height - 12)
              }
              r="2"
              fill={color}
            />
          ) : null,
        )}
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="chart-axis">
        <span>{values.length} / 60 sample slots</span>
        <span>{values.length < 2 ? "Collecting history…" : "Now"}</span>
      </div>
    </div>
  );
}
function MetricCard({
  title,
  icon,
  value,
  unit,
  note,
  percent,
}: {
  title: string;
  icon: ReactNode;
  value: ReactNode;
  unit?: string;
  note: ReactNode;
  percent?: number | null;
}) {
  return (
    <section
      className={`metric-card ${percent != null && percent >= 95 ? "critical" : percent != null && percent >= 85 ? "warning" : ""}`}
    >
      <div className="metric-label">
        {title}
        {icon}
      </div>
      <div className="metric-value">
        {value}
        <span>{unit}</span>
      </div>
      {percent !== undefined && (
        <div className="progress">
          <div
            style={{ width: `${Math.min(Math.max(percent ?? 0, 0), 100)}%` }}
          />
        </div>
      )}
      <div className="metric-note">{note}</div>
    </section>
  );
}
function Detail({ name, m }: { name: string; m: Metric | undefined }) {
  return (
    <div className="detail">
      <span>{name}</span>
      <div>
        <Reading m={m} />
        <small> {m?.value != null && m?.unit !== "text" ? m.unit : ""}</small>
        {m?.value == null && (
          <small className="unavailable">
            {m?.reason || "Waiting for telemetry"}
          </small>
        )}
      </div>
    </div>
  );
}
function App() {
  const [page, setPage] = useState("Overview");
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const {
    snapshot: s,
    history,
    connected,
    age,
    stale,
    invalid,
  } = useTelemetry();
  const d = s?.data;
  const series = (get: (s: Snapshot) => number | null) =>
    history.map((x) => (x === null ? null : get(x)));
  const traffic = (s: Snapshot, key: "rx" | "tx") => {
    const v = s.data.network.interfaces
      .filter((i) => i.name !== "lo")
      .map((i) => (i[key].stale ? null : i[key].value));
    return v.length && v.every((n) => n !== null)
      ? v.reduce<number>((a, b) => a + (b ?? 0), 0)
      : null;
  };
  const networkSeries = series((x) => traffic(x, "rx"));
  const networkMax =
    Math.max(
      1024,
      ...networkSeries.filter((n): n is number => n !== null),
      ...series((x) => traffic(x, "tx")).filter((n): n is number => n !== null),
    ) * 1.2;
  const rawFrequency = d?.cpu.frequencies
    .map((f) => f.value)
    .filter((v): v is number => v !== null);
  const cpuFrequency = rawFrequency?.length
    ? Math.round(rawFrequency.reduce((a, b) => a + b, 0) / rawFrequency.length)
    : null;
  const volume = d?.storage.volumes[0];
  const cpuPanel = (
    <Panel
      title="CPU utilization"
      icon={<Cpu size={16} />}
      aside={
        <span className="legend">
          <i />
          Overall · %
        </span>
      }
    >
      <div className="plot-value">
        <Reading m={d?.cpu.overall} />
        <span>%</span>
        <small>{d?.cpu.cores.length ?? "—"} logical cores</small>
      </div>
      <Chart
        values={series((x) =>
          x.data.cpu.overall.stale ? null : x.data.cpu.overall.value,
        )}
        label="CPU utilization history"
      />
      <p className="source-note">
        {
          history.filter(
            (x) =>
              x === null ||
              x.data.cpu.overall.value === null ||
              x.data.cpu.overall.stale,
          ).length
        }{" "}
        unavailable/stale samples in this window · gaps are not interpolated.
      </p>
      <div className="core-grid">
        {d?.cpu.cores.map((c, i) => (
          <div className="core" key={i}>
            <div>
              <span>
                {d?.cpu.core_ids.value
                  ? `CPU ${d.cpu.core_ids.value[i]}`
                  : `Core ${i}`}
              </span>
              <b>
                <Reading m={c} />%
              </b>
            </div>
            <div className="progress">
              <div style={{ width: `${c.value ?? 0}%` }} />
            </div>
          </div>
        ))}
      </div>
    </Panel>
  );
  const bpuPanel = (
    <Panel
      title="BPU utilization"
      icon={<Zap size={16} />}
      aside={<span className="secondary">Native ratio · %</span>}
    >
      <div className="bpu-load">
        <div
          className="bpu-gauge"
          role="meter"
          aria-label="BPU utilization"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={d?.bpu.utilization.value ?? undefined}
          style={{
            background: `conic-gradient(#45c8f3 ${Math.max(0, Math.min(100, d?.bpu.utilization.value ?? 0)) * 3.6}deg, #233348 0deg)`,
          }}
        >
          <div>
            <Reading m={d?.bpu.utilization} />
            <small>%</small>
          </div>
        </div>
        <div className="bpu-temperature-summary">
          <Detail name="Dedicated BPU temperature" m={d?.bpu.temperature} />
          <Detail
            name="CPU-temperature proxy"
            m={d?.bpu.cpu_temperature_proxy}
          />
          <small>
            CPU proxy is not an independently measured BPU temperature.
          </small>
        </div>
      </div>
      <Chart
        values={series((x) =>
          x.data.bpu.utilization.stale ? null : x.data.bpu.utilization.value,
        )}
        label="BPU utilization history"
      />
      <p className="source-note">
        {d?.bpu.utilization.reason || d?.bpu.utilization.source} · Physical
        inference-load validation pending.
      </p>
    </Panel>
  );
  const ramPanel = (
    <Panel
      title="Memory"
      icon={<Layers size={16} />}
      aside={<span className="secondary">RAM · %</span>}
    >
      <div className="plot-value">
        <Reading m={d?.memory.percent} />
        <span>%</span>
        <small>
          {bytes(d?.memory.used.value)} / {bytes(d?.memory.total.value)}
        </small>
      </div>
      <Chart
        values={series((x) =>
          x.data.memory.percent.stale ? null : x.data.memory.percent.value,
        )}
        label="RAM utilization history"
        color="#9286fa"
      />
      <div className="panel-foot">
        <span>Available memory</span>
        <b>{bytes(d?.memory.available.value)}</b>
      </div>
    </Panel>
  );
  const thermalPanel = (
    <Panel
      title="Thermals"
      icon={<Thermometer size={16} />}
      aside={<span className="secondary">°C</span>}
    >
      <div className="thermal-values">
        <div>
          <span className="legend">
            <i />
            CPU
          </span>
          <strong>
            <Reading m={d?.thermal.cpu} />
            <small> °C</small>
          </strong>
        </div>
        <div>
          <span className="legend violet">
            <i />
            DDR
          </span>
          <strong>
            <Reading m={d?.thermal.ddr} />
            <small> °C</small>
          </strong>
        </div>
      </div>
      <Chart
        values={series((x) =>
          x.data.thermal.cpu.stale ? null : x.data.thermal.cpu.value,
        )}
        max={100}
        label="CPU temperature history"
      />
      <Chart
        values={series((x) =>
          x.data.thermal.ddr.stale ? null : x.data.thermal.ddr.value,
        )}
        max={100}
        color="#9286fa"
        label="DDR temperature history"
      />
      <p className="source-note">
        Discovered by thermal zone type · millidegrees → °C
      </p>
    </Panel>
  );
  const networkPanel = (
    <Panel
      title="Network traffic"
      icon={<Activity size={16} />}
      aside={<span className="secondary">All interfaces except loopback</span>}
    >
      <div className="network-values">
        <div>
          <ArrowDownLeft size={15} />
          <span>Receive</span>
          <b>
            {s ? bytes(traffic(s, "rx")) : "—"}
            <small>/s</small>
          </b>
        </div>
        <div>
          <ArrowUpRight size={15} />
          <span>Transmit</span>
          <b>
            {s ? bytes(traffic(s, "tx")) : "—"}
            <small>/s</small>
          </b>
        </div>
      </div>
      <Chart
        values={networkSeries}
        max={networkMax}
        label="Network receive throughput"
      />
      <Chart
        values={series((x) => traffic(x, "tx"))}
        max={networkMax}
        color="#9286fa"
        label="Network transmit throughput"
      />
    </Panel>
  );
  const servicesPanel = (
    <Panel
      title="Runtime services"
      icon={<Server size={16} />}
      aside={<span className="secondary">Native host</span>}
    >
      {["docker", "containerd"].map((name) => (
        <div className="service-row" key={name}>
          <div className="service-icon">
            <Box size={18} />
          </div>
          <div>
            <b>{name === "docker" ? "Docker Engine" : "containerd"}</b>
            <small>{d?.services[name].source || "Waiting for telemetry"}</small>
          </div>
          <Status
            ok={
              d?.services[name].value
                ? d.services[name].value?.active === "active"
                : null
            }
            label={
              d?.services[name].stale
                ? "Stale"
                : d?.services[name].value?.active
            }
          />
        </div>
      ))}
      <p className="source-note">
        Service state only. Container inventory is unavailable.
      </p>
    </Panel>
  );
  let content: ReactNode;
  if (page === "Overview")
    content = (
      <>
        <div className="metrics">
          <MetricCard
            title="CPU utilization"
            icon={<Cpu size={19} />}
            value={<Reading m={d?.cpu.overall} />}
            unit="%"
            percent={d?.cpu.overall.value}
            note={`${d?.cpu.cores.length ?? "—"} cores · ${fmt(cpuFrequency, 0)} MHz mean`}
          />
          <MetricCard
            title="Memory usage"
            icon={<Layers size={19} />}
            value={<Reading m={d?.memory.percent} />}
            unit="%"
            percent={d?.memory.percent.value}
            note={`${bytes(d?.memory.used.value)} of ${bytes(d?.memory.total.value)}`}
          />
          <MetricCard
            title="CPU temperature"
            icon={<Thermometer size={19} />}
            value={<Reading m={d?.thermal.cpu} />}
            unit="°C"
            note={
              d?.thermal.cpu.value == null
                ? "Thermal sensor unavailable"
                : "thermal-cpu · sysfs"
            }
          />
          <MetricCard
            title="Storage usage"
            icon={<HardDrive size={19} />}
            value={<Reading m={volume?.percent} />}
            unit="%"
            percent={volume?.percent.value}
            note={`${bytes(volume?.free.value)} free · ${volume?.path ?? "/"}`}
          />
        </div>
        <div className="dashboard-grid">
          {cpuPanel}
          {ramPanel}
          {thermalPanel}
          {networkPanel}
        </div>
        {bpuPanel}
        <div className="frequency-strip">
          {[
            ["CPU", cpuFrequency, "Mean of available core frequencies"],
            [
              "BPU",
              d?.bpu.frequency.current.value,
              "devfreq · not utilization",
            ],
            [
              "GPU",
              d?.frequencies.gpu.current.value,
              "devfreq · current frequency",
            ],
            [
              "DDR",
              d?.frequencies.ddr.current.value,
              "devfreq · current frequency",
            ],
          ].map(([n, v, note]) => (
            <div key={String(n)}>
              <span>
                <Zap size={14} />
                {n} frequency
              </span>
              <b>
                {v == null ? (
                  <span className="missing-value">Unavailable</span>
                ) : (
                  fmt(v)
                )}{" "}
                <small>MHz</small>
              </b>
              <small>{note}</small>
            </div>
          ))}
        </div>
        <div className="dashboard-grid lower">
          {servicesPanel}
          <Panel title="Platform identity" icon={<Cpu size={16} />}>
            <Detail name="Hostname" m={d?.system.hostname} />
            <Detail name="Operating system" m={d?.system.os} />
            <Detail name="Kernel" m={d?.system.kernel} />
            <Detail name="Architecture" m={d?.system.architecture} />
            <Detail name="Uptime" m={d?.system.uptime} />
          </Panel>
        </div>
      </>
    );
  else if (page === "Hardware")
    content = (
      <>
        <div className="dashboard-grid">
          {cpuPanel}
          {ramPanel}
          {thermalPanel}
          <Panel title="Storage volumes" icon={<HardDrive size={16} />}>
            {d?.storage.volumes.map((v) => (
              <div key={v.path}>
                <h3>{v.path}</h3>
                <Detail name="Used" m={v.percent} />
                <div className="detail">
                  <span>Free / total</span>
                  <b>
                    {bytes(v.free.value)} / {bytes(v.total.value)}
                  </b>
                </div>
              </div>
            ))}
          </Panel>
        </div>
        <Panel title="Cooling device states">
          {d?.thermal.cooling_devices.value?.map((c) => (
            <Detail
              key={c.name}
              name={`${c.name} · ${c.type.value}`}
              m={c.state}
            />
          ))}
          {!d?.thermal.cooling_devices.value?.length && (
            <p className="empty">No cooling devices reported.</p>
          )}
        </Panel>
        <Panel title="Core frequencies">
          {d?.cpu.frequencies.map((f, i) => (
            <Detail
              key={i}
              name={
                d?.cpu.core_ids.value
                  ? `CPU ${d.cpu.core_ids.value[i]}`
                  : `Core sample ${i}`
              }
              m={f}
            />
          ))}
        </Panel>
      </>
    );
  else if (page === "Cameras")
    content = (
      <>
        <div className="notice">
          <ShieldCheck size={19} />
          <div>
            <b>Passive camera monitoring</b>
            <p>
              Discovery checks publishers and the /mipi_cam node. It does not
              start capture or subscribe to raw images. Publisher presence does
              not confirm image quality or frame rate.
            </p>
          </div>
        </div>
        <Panel
          title="GS130WI stereo camera"
          icon={<Camera size={18} />}
          aside={
            <Status
              ok={
                d?.cameras.node_present.stale
                  ? null
                  : d?.cameras.node_present.value
              }
              label={d?.cameras.node_present.stale ? "Stale" : undefined}
            />
          }
        >
          <Detail name="/mipi_cam node present" m={d?.cameras.node_present} />
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Known topic</th>
                  <th>Publishers</th>
                  <th>Availability</th>
                </tr>
              </thead>
              <tbody>
                {d?.cameras.topics.map((t) => (
                  <tr key={t.name}>
                    <td className="mono">{t.name}</td>
                    <td>
                      <Reading m={t.publishers} digits={0} />
                    </td>
                    <td>
                      <Status
                        ok={
                          t.publishers.value == null
                            ? null
                            : t.publishers.value > 0
                        }
                        label={t.publishers.stale ? "Stale" : undefined}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </>
    );
  else if (page === "BPU")
    content = (
      <>
        <div className="notice">
          <Zap size={19} />
          <div>
            <b>Frequency is not accelerator utilization</b>
            <p>
              Utilization is read directly from the BPU ratio interface.
              Dedicated temperature can be unavailable; any CPU-temperature
              proxy is labeled separately. Physical inference-load validation
              remains pending.
            </p>
          </div>
        </div>
        {bpuPanel}
        <div className="dashboard-grid">
          <Panel title="BPU interfaces" icon={<Zap size={18} />}>
            <Detail name="Current frequency" m={d?.bpu.frequency.current} />
            <Detail name="Minimum frequency" m={d?.bpu.frequency.min} />
            <Detail name="Maximum frequency" m={d?.bpu.frequency.max} />
            <Detail name="Governor" m={d?.bpu.frequency.governor} />
            <Detail
              name="Available frequencies"
              m={d?.bpu.frequency.available_frequencies}
            />
            <Detail
              name="Available governors"
              m={d?.bpu.frequency.available_governors}
            />
            <Detail name="Utilization" m={d?.bpu.utilization} />
            <Detail name="Dedicated BPU temperature" m={d?.bpu.temperature} />
            <Detail
              name="CPU-temperature proxy"
              m={d?.bpu.cpu_temperature_proxy}
            />
            <Detail
              name="Temperature fallback status"
              m={d?.bpu.temperature_fallback}
            />
          </Panel>
          <Panel title="Device availability">
            <Status
              ok={d?.bpu.devices.value ? d.bpu.devices.value.length > 0 : null}
            />
            {d?.bpu.devices.value?.map((v) => (
              <div className="detail" key={v.path}>
                <code>{v.path}</code>
                <span>
                  {v.readable ? "Readable" : "Present · permission restricted"}
                </span>
              </div>
            ))}
            {!d?.bpu.devices.value && (
              <p className="empty">
                {d?.bpu.devices.reason || "Waiting for telemetry"}
              </p>
            )}
          </Panel>
        </div>
        <div className="dashboard-grid">
          {["gpu", "ddr"].map((name) => (
            <Panel
              key={name}
              title={`${name.toUpperCase()} frequency interface`}
            >
              {Object.entries(d?.frequencies[name as "gpu" | "ddr"] ?? {}).map(
                ([k, m]) => (
                  <Detail key={k} name={k.replaceAll("_", " ")} m={m} />
                ),
              )}
            </Panel>
          ))}
        </div>
      </>
    );
  else if (page === "ROS2")
    content = (
      <>
        <div className="notice">
          <Radio size={19} />
          <div>
            <b>Native ROS2 graph discovery</b>
            <p>
              Discovery runs in the sourced Humble environment. Graph samples
              refresh separately from hardware telemetry; each value includes
              its own age.
            </p>
          </div>
        </div>
        <div className="dashboard-grid">
          <Panel
            title="ROS2 environment"
            aside={<Status ok={d?.ros2.available.value} />}
          >
            {d?.ros2.nodes.stale && (
              <p className="amber">
                Last successful graph retained · stale discovery data.
              </p>
            )}
            <Detail name="Discovery available" m={d?.ros2.available} />
            <Detail name="Discovery duration" m={d?.ros2.probe_duration} />
            <Detail name="Last successful discovery" m={d?.ros2.last_success} />
            <Detail
              name="Consecutive discovery failures"
              m={d?.ros2.consecutive_failures}
            />
            <Detail name="Discovery diagnostic" m={d?.ros2.diagnostic} />
            <Detail name="Diagnostic reason" m={d?.ros2.detail} />
            {d?.ros2.stderr_excerpt?.value && (
              <Detail
                name="Sanitized probe stderr"
                m={d?.ros2.stderr_excerpt}
              />
            )}
            <Detail
              name="Graph age"
              m={
                d?.ros2.nodes
                  ? {
                      ...d.ros2.nodes,
                      value: d.ros2.nodes.age_seconds,
                      unit: "s",
                    }
                  : undefined
              }
            />
            {d?.ros2.nodes.value?.map((n) => (
              <div className="detail mono" key={n}>
                {n}
              </div>
            ))}
          </Panel>
          <Panel title="Native setup locations">
            <p className="empty mono">
              /opt/ros/humble/
              <br />
              /opt/tros/humble/
            </p>
            <p className="source-note">
              No ROS2 configuration changes or camera startup.
            </p>
          </Panel>
        </div>
        <Panel title="Discovered topics">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Topic</th>
                  <th>Message type</th>
                  <th>Publishers</th>
                </tr>
              </thead>
              <tbody>
                {d?.ros2.topics.value?.map((t) => (
                  <tr key={t.name}>
                    <td className="mono">{t.name}</td>
                    <td className="mono">{t.types.join(", ")}</td>
                    <td>{t.publishers}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d?.ros2.topics.value == null && (
            <p className="empty">{d?.ros2.topics.reason}</p>
          )}
        </Panel>
      </>
    );
  else if (page === "Network")
    content = (
      <>
        {networkPanel}
        <Panel title="Host interfaces" icon={<Wifi size={18} />}>
          {d?.network.interfaces.map((i) => (
            <div className="interface" key={i.name}>
              <h3>
                {i.name}{" "}
                <Status
                  ok={i.up.value}
                  label={i.up.stale ? "Stale" : i.up.value ? "Up" : "Down"}
                />
              </h3>
              <Detail name="Addresses" m={i.addresses} />
              <div className="detail">
                <span>Receive / transmit</span>
                <b>
                  {bytes(i.rx.value)}/s / {bytes(i.tx.value)}/s
                </b>
              </div>
              <p className="source-note">{i.rx.reason || i.rx.source}</p>
            </div>
          ))}
        </Panel>
        <div className="notice">
          <ShieldCheck size={19} />
          <p>
            Interface configuration, firewall rules and routes are read-only and
            remain under host administration.
          </p>
        </div>
      </>
    );
  else if (page === "Containers")
    content = (
      <>
        {servicesPanel}
        <Panel title="Container inventory" icon={<Box size={18} />}>
          <div className="empty">
            <Box size={35} />
            <h3>Inventory unavailable in v{releaseVersion}</h3>
            <p>
              The native agent reports Docker and containerd service status.
              Container listing and lifecycle controls are outside this release.
              The dashboard has no Docker socket access.
            </p>
          </div>
        </Panel>
      </>
    );
  else if (page === "Diagnostics") {
    const rows: { path: string; m: Metric }[] = [];
    const walk = (v: unknown, p: string) => {
      if (v && typeof v === "object") {
        if ("unit" in v && "status" in v) {
          rows.push({ path: p, m: v as Metric });
        } else
          Object.entries(v).forEach(([k, x]) => walk(x, p ? `${p}.${k}` : k));
      }
    };
    if (d) walk(d, "");
    content = (
      <>
        <div className="notice">
          <Activity size={19} />
          <div>
            <b>Collector health</b>
            <p>
              {s?.collector_error || "No collector error reported"} · Sample{" "}
              {s?.sequence ?? "—"} · Last collection{" "}
              {s?.collection_seconds ?? "—"} s ·{" "}
              {rows.filter((r) => r.m.value === null).length} unavailable values
            </p>
          </div>
        </div>
        <Panel title="Measurement diagnostics">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Measurement</th>
                  <th>Status / age</th>
                  <th>Source / explanation</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.path}>
                    <td className="mono">{r.path}</td>
                    <td>
                      <span
                        className={
                          r.m.stale || r.m.status !== "ok" ? "amber" : "green"
                        }
                      >
                        {r.m.stale ? "stale" : r.m.status}
                      </span>
                      <small className="block">
                        {r.m.age_seconds.toFixed(1)} s
                      </small>
                    </td>
                    <td>
                      {r.m.source}
                      <small className="block">{r.m.reason}</small>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </>
    );
  } else
    content = (
      <>
        <Panel title="RDK Control Center" icon={<Cpu size={20} />}>
          <div className="about">
            <div className="about-logo">
              <Cpu size={46} />
            </div>
            <h3>Infrastructure for your robotics.</h3>
            <p>
              Version {releaseVersion} · Independent application for D-Robotics
              RDK X5.
            </p>
            <p>
              A native Python agent keeps hardware interfaces and ROS2 on the
              host. A lightweight React dashboard runs behind a local Nginx
              reverse proxy in Docker.
            </p>
            <div className="about-tags">
              <span>Read-only</span>
              <span>ARM64 target</span>
              <span>No BlueOS dependency</span>
            </div>
            <p className="amber">
              Real RDK X5 validation is pending. Mock fixtures are for
              development only.
            </p>
            <p>
              Unauthenticated monitoring is intended for loopback access or an
              SSH tunnel. LAN access requires a trusted network and explicit
              configuration.
            </p>
          </div>
        </Panel>
        <Panel title="Interface references">
          <a
            className="reference"
            href="https://developer.d-robotics.cc/rdk_x_doc/en/Advanced_development/linux_development/driver_development_x5/driver_lowpower"
            target="_blank"
            rel="noreferrer"
          >
            D-Robotics frequency interfaces <ExternalLink size={14} />
          </a>
          <a
            className="reference"
            href="https://docs.ros.org/en/humble/index.html"
            target="_blank"
            rel="noreferrer"
          >
            ROS2 Humble documentation <ExternalLink size={14} />
          </a>
        </Panel>
      </>
    );
  return (
    <div
      className={`app ${collapsed ? "collapsed" : ""} ${mobile ? "mobile-open" : ""}`}
    >
      <aside className="sidebar">
        <a
          href="#"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            setPage("Overview");
          }}
        >
          <div className="brand-icon">
            <Cpu size={24} />
          </div>
          <div>
            <b>
              RDK<span> CONTROL CENTER</span>
            </b>
            <small>ROBOTICS MANAGEMENT</small>
          </div>
        </a>
        <div className="sidebar-section">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {pages.map(([name, Icon]) => (
            <button
              key={name}
              className={page === name ? "active" : ""}
              title={name}
              aria-current={page === name ? "page" : undefined}
              onClick={() => {
                setPage(name);
                setMobile(false);
                window.scrollTo(0, 0);
              }}
            >
              <Icon size={19} />
              <span>{name}</span>
              {name === "Overview" && <i />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="target-label">
            <Cpu size={17} />
            <div>
              <b>D-Robotics RDK X5</b>
              <small>
                {s?.mode === "mock" ? "SIMULATED TARGET" : "NATIVE HOST"}
              </small>
            </div>
          </div>
          <div className="sidebar-version">
            <span>v{releaseVersion}</span>
            <button
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <ChevronRight size={17} />
              ) : (
                <ChevronLeft size={17} />
              )}
            </button>
          </div>
        </div>
      </aside>
      {mobile && (
        <button
          className="scrim"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="mobile-toggle"
              aria-label="Toggle navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={20} /> : <Menu size={20} />}
            </button>
            <span className="breadcrumb">
              Workspace <ChevronRight size={14} /> <b>{page}</b>
            </span>
          </div>
          <div className="topbar-right">
            <span className="readonly">
              <ShieldCheck size={14} />
              Read-only
            </span>
            <span className="top-divider" />
            <Status
              ok={connected && !stale}
              label={
                connected
                  ? stale
                    ? "Stale telemetry"
                    : "Connected"
                  : "Reconnecting"
              }
            />
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">RDK X5 / CONTROL CENTER</div>
              <h1>{page}</h1>
              <p>{subtitles[page]}</p>
            </div>
            <div className="live-info">
              <span className="live-chip">
                <Activity size={14} />
                {s ? `${s.interval_seconds}s telemetry` : "Awaiting telemetry"}
              </span>
              <small>
                Updated {s ? new Date(s.timestamp).toLocaleTimeString() : "—"}
              </small>
            </div>
          </div>
          {s?.mode === "mock" && (
            <div className="mock-banner" role="status">
              <div>
                <Code2 size={18} />
                <b>MOCK DATA</b>
                <span>
                  Simulated RDK X5 · Hardware measurements are illustrative.
                </span>
              </div>
              <span className="mock-tag">DEVELOPMENT MODE</span>
            </div>
          )}
          {(!connected || stale) && (
            <div className="connection-alert" role="alert">
              {stale ? "STALE DATA · " : "Connection unavailable · "}
              {s
                ? `Last sample ${Math.floor(age)}s ago. Readings are retained; waiting for fresh telemetry.`
                : "Waiting for the native monitoring agent. Reconnection is automatic."}
            </div>
          )}
          {invalid && (
            <div className="connection-alert" role="alert">
              Incomplete telemetry unavailable; waiting for a complete sample.
            </div>
          )}
          {content}
          <footer>
            <span>
              <ShieldCheck size={13} /> Native monitoring · Hardware remains on
              the host
            </span>
            <span>
              {s?.mode === "mock" ? "Mock fixtures" : "Local agent"} <i /> v
              {releaseVersion}
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
class DashboardBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Dashboard rendering failed", error, info);
  }
  render() {
    return this.state.failed ? (
      <main role="alert">
        Dashboard unavailable. Reload to retry; telemetry may be incomplete.
      </main>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <DashboardBoundary>
      <App />
    </DashboardBoundary>
  </StrictMode>,
);

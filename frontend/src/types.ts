export interface Metric<T = unknown> {
  value: T | null;
  unit: string;
  status: "ok" | "unavailable" | "error" | "warming_up";
  reason: string | null;
  source: string;
  timestamp: string;
  age_seconds: number;
  stale: boolean;
}
export interface Frequency {
  current: Metric<number>;
  min: Metric<number>;
  max: Metric<number>;
  governor: Metric<string>;
  available_frequencies: Metric<number[]>;
  available_governors: Metric<string[]>;
}
export interface Topic {
  name: string;
  types: string[];
  publishers: number;
}
export interface Snapshot {
  version: string;
  mode: "mock" | "native";
  timestamp: string;
  sequence: number;
  interval_seconds: number;
  stale_after_seconds: number;
  stale: boolean;
  age_seconds: number;
  collector_error: string | null;
  collection_seconds: number;
  data: {
    system: Record<string, Metric>;
    cpu: {
      overall: Metric<number>;
      core_ids: Metric<number[]>;
      cores: Metric<number>[];
      frequencies: Metric<number>[];
      load_average: Metric<number[]>;
    };
    memory: Record<string, Metric<number>>;
    storage: {
      volumes: {
        path: string;
        total: Metric<number>;
        used: Metric<number>;
        free: Metric<number>;
        percent: Metric<number>;
      }[];
    };
    thermal: {
      cpu: Metric<number>;
      ddr: Metric<number>;
      cooling_devices: Metric<
        {
          name: string;
          type: Metric<string>;
          state: Metric<number>;
          max_state: Metric<number>;
        }[]
      >;
    };
    bpu: {
      devices: Metric<{ path: string; readable: boolean }[]>;
      frequency: Frequency;
      utilization: Metric<number>;
      temperature: Metric<number>;
      cpu_temperature_proxy: Metric<number>;
      temperature_fallback: Metric<string>;
    };
    frequencies: { gpu: Frequency; ddr: Frequency };
    network: {
      interfaces: {
        name: string;
        up: Metric<boolean>;
        addresses: Metric<string[]>;
        rx: Metric<number>;
        tx: Metric<number>;
      }[];
    };
    services: Record<string, Metric<{ active: string; sub: string }>>;
    ros2: {
      available: Metric<boolean>;
      probe_duration: Metric<number>;
      last_success: Metric<string>;
      consecutive_failures: Metric<number>;
      diagnostic: Metric<string>;
      detail: Metric<string>;
      stderr_excerpt: Metric<string>;
      nodes: Metric<string[]>;
      topics: Metric<Topic[]>;
    };
    cameras: {
      node_present: Metric<boolean>;
      topics: { name: string; publishers: Metric<number> }[];
      capture: Metric;
    };
  };
}

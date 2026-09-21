export interface AuthState {
  configured: boolean;
  authenticated: boolean;
}

export type DeviceType = "usb" | "emulator" | "wireless";

export interface Device {
  id: string;
  type: DeviceType;
  model?: string | null;
  serial?: string | null;
  ip?: string | null;
  port?: string | null;
  disabled: boolean;
  online: boolean;
}

export interface PendingDevice {
  id: string;
  state: "unauthorized" | "offline";
}

export interface DeviceList {
  devices: Device[];
  pending: PendingDevice[];
}

export interface DiscoverResult {
  added: string[];
  pending: { ip: string; port: string }[];
  devices: Device[];
}

export interface Telemetry {
  battery: string;
  charging: boolean | null;
  screen: string;
  android: string;
  storage: string;
  app: string;
  model: string;
}

export interface SystemInfo {
  version: string;
  python: string;
  platform: { linux: boolean; macos: boolean; wsl: boolean };
  adb: { windows_exe: string | null; server_port: number };
  data_dir: string;
  reach: string;
  port: number;
}

export interface SessionSummary {
  id: string;
  project: string;
  device: string;
  status: string;
}

export interface DeviceEvent {
  type: "devices";
  devices: Device[];
  pending: PendingDevice[];
  sessions: SessionSummary[];
}

export interface Project {
  path: string;
  port: string;
  api_local: string;
  api_remote?: string;
  socket_local?: string;
  socket_remote?: string;
  additional_ports?: string[];
  backend?: { path: string; cmd: string };
  package?: string;
}

export type RunStatus = "starting" | "running" | "stopping" | "stopped" | "finished" | "crashed" | "lost";

export interface Run {
  id: string;
  project: string;
  device: string;
  serial: string | null;
  mode: "local" | "remote";
  status: RunStatus;
  pid: number | null;
  vm_service: string | null;
  devtools: string | null;
  exit_code: number | null;
  started_at: string;
  ended_at: string | null;
}

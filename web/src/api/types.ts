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

export interface Thread {
  thread_id: string;
  address: string;
  label: string;
  date: string;
  when: string;
  count: string;
  unread: number;
  snippet: string;
}

export interface Message {
  id: string;
  address: string;
  label: string;
  when: string;
  date: string;
  direction: string;
  read: boolean;
  body: string;
}

export interface Call {
  id: string;
  number: string;
  label: string;
  when: string;
  date: string;
  kind: string;
  duration: string;
  new: boolean;
}

export interface Contact {
  id: string;
  name: string;
  number: string;
}

export interface Calendar {
  id: string;
  name: string;
  account: string;
}

export interface CalendarEvent {
  id: string;
  title: string;
  when: string;
  begin: string;
  end: string;
  all_day: boolean;
  where: string;
  calendar_id: string;
}

export interface DeviceInfo {
  props: Record<string, string>;
  battery: Record<string, string>;
  storage: string;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "dir" | "file" | "link";
  size: number;
  modified: string;
  mode: string;
  owner: string;
  group: string;
}

export interface FileList {
  path: string;
  parent: string;
  entries: FileEntry[];
}

export interface Settings {
  reach: string;
  reach_label: string;
  reach_levels: { id: string; label: string }[];
  port: number;
  remote_domain: string;
  urls: string[];
  notes: string[];
  token: string | null;
  restart_required: boolean;
}

export interface ToolCheck {
  name: string;
  purpose: string;
  present: boolean;
  version: string;
  path: string;
  required: boolean;
  installable: boolean;
  requires_sudo: boolean;
  manual: string | null;
}

export interface DoctorReport {
  platform: { linux: boolean; wsl: boolean; macos: boolean };
  adb: { windows_exe: string | null; server_port: number };
  tools: ToolCheck[];
  notes: { tone: string; text: string }[];
}

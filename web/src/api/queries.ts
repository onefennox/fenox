import { api } from "./client";
import type {
  AuthState,
  Calendar,
  CalendarEvent,
  Call,
  Contact,
  Device,
  DeviceInfo,
  DeviceList,
  DiscoverResult,
  DoctorReport,
  FileList,
  Message,
  Project,
  Run,
  Settings,
  SystemInfo,
  Telemetry,
  ToolsReport,
  Thread,
} from "./types";

export const keys = {
  auth: ["auth"] as const,
  devices: ["devices"] as const,
  device: (id: string) => ["device", id] as const,
  telemetry: (id: string) => ["telemetry", id] as const,
  system: ["system"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  apps: (id: string) => ["apps", id] as const,
  info: (id: string) => ["device-info", id] as const,
  processes: (id: string) => ["processes", id] as const,
  messages: (id: string) => ["messages", id] as const,
  conversation: (id: string, thread: string) => ["messages", id, thread] as const,
  calls: (id: string) => ["calls", id] as const,
  contacts: (id: string) => ["contacts", id] as const,
  calendars: (id: string) => ["calendars", id] as const,
  events: (id: string) => ["events", id] as const,
};

export const getAuth = () => api.get<AuthState>("/api/auth/me");
export const setupOwner = (password: string) => api.post<AuthState>("/api/setup", { password });
export const login = (password: string, remember: boolean) =>
  api.post<AuthState>("/api/auth/login", { password, remember });
export const logout = () => api.post<AuthState>("/api/auth/logout");

export const getSystem = () => api.get<SystemInfo>("/api/system");

export const listDevices = () => api.get<DeviceList>("/api/devices");
export const discoverDevices = (mode: "all" | "usb" | "wireless" = "all") =>
  api.post<DiscoverResult>(`/api/devices/discover?mode=${mode}`);
export const connectWireless = (ip: string, port: string) =>
  api.post<Device>("/api/devices/connect-wireless", { ip, port });
export const connectDevice = (id: string) => api.post<Device>(`/api/devices/${id}/connect`);
export const pairDevice = (ip: string, port: string, code: string) =>
  api.post<{ paired: boolean; detail: string }>("/api/devices/pair", { ip, port, code });
export const updateDevice = (id: string, patch: Partial<Device> & { name?: string }) =>
  api.patch<Device>(`/api/devices/${id}`, patch);
export const deleteDevice = (id: string) => api.delete<void>(`/api/devices/${id}`);
export const getTelemetry = (id: string) => api.get<{ telemetry: Telemetry }>(`/api/devices/${id}/telemetry`);

export const listProjects = () => api.get<{ projects: Record<string, Project> }>("/api/projects");
export const getProject = (id: string) => api.get<{ id: string; project: Project }>(`/api/projects/${id}`);
export const createProject = (payload: { name: string; path: string; update?: boolean }) =>
  api.post<{ id: string; project: Project }>("/api/projects", payload);
export const updateProject = (id: string, patch: Partial<Project>) =>
  api.patch<{ id: string; project: Project }>(`/api/projects/${id}`, patch);
export const deleteProject = (id: string) => api.delete<void>(`/api/projects/${id}`);
export const scanProjects = () => api.post<{ added: string[]; projects: Record<string, Project> }>("/api/projects/scan");

export const listRuns = () => api.get<{ runs: Run[] }>("/api/runs");
export const getRun = (id: string) => api.get<Run>(`/api/runs/${id}`);
export const startRun = (project: string, device: string, mode: "local" | "remote") =>
  api.post<Run>("/api/runs", { project, device, mode });
export const startBatchRun = (project: string, mode: "local" | "remote") =>
  api.post<{ started: Run[]; failed: { device: string; error: string }[] }>("/api/runs/batch", { project, mode });
export const controlRun = (id: string, action: "reload" | "restart" | "stop") =>
  api.post<{ ok: boolean }>(`/api/runs/${id}/${action}`);

// -- device actions --------------------------------------------------------

const devicePath = (id: string) => `/api/devices/${encodeURIComponent(id)}`;

export const wakeDevice = (id: string) => api.post<{ ok: boolean }>(`${devicePath(id)}/wake`);
export const lockDevice = (id: string) => api.post<{ ok: boolean }>(`${devicePath(id)}/lock`);
export const sendInput = (id: string, body: Record<string, unknown>) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/input`, body);
export const openUrl = (id: string, url: string) => api.post<{ ok: boolean }>(`${devicePath(id)}/open-url`, { url });
export const readClipboard = (id: string) => api.get<{ clipboard: string }>(`${devicePath(id)}/clipboard`);
export const writeClipboard = (id: string, text: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/clipboard`, { text });

export const listApps = (id: string) => api.get<{ apps: string[] }>(`${devicePath(id)}/apps`);
export const installApp = (id: string, path: string) =>
  api.post<{ ok: boolean; detail: string }>(`${devicePath(id)}/apps/install`, { path });
export const uninstallApp = (id: string, pkg: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/apps/${encodeURIComponent(pkg)}/uninstall`);
export const clearApp = (id: string, pkg: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/apps/${encodeURIComponent(pkg)}/clear`);
export const stopApp = (id: string, pkg: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/apps/${encodeURIComponent(pkg)}/stop`);
export const launchApp = (id: string, pkg: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/apps/${encodeURIComponent(pkg)}/launch`);
export const appInfo = (id: string, pkg: string) =>
  api.get<{ info: string }>(`${devicePath(id)}/apps/${encodeURIComponent(pkg)}/info`);

export const rebootDevice = (id: string, mode: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/reboot`, { mode });
export const toggleService = (id: string, service: string, enabled: boolean) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/toggle`, { service, enabled });
export const setVolume = (id: string, level: number) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/volume`, { level });
export const setBrightness = (id: string, level: number) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/brightness`, { level });
export const runShell = (id: string, command: string) =>
  api.post<{ ok: boolean; output: string }>(`${devicePath(id)}/shell`, { command });

export const getInfo = (id: string) => api.get<DeviceInfo>(`${devicePath(id)}/info`);
export const getProcesses = (id: string) => api.get<{ processes: string[] }>(`${devicePath(id)}/processes`);
export const sendNotification = (id: string, title: string, text: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/notification`, { title, text });
export const readNotifications = (id: string) =>
  api.get<{ notifications: string }>(`${devicePath(id)}/notifications`);

// -- phone data ------------------------------------------------------------

export const getThreads = (id: string, unread = false) =>
  api.get<{ threads: Thread[] }>(`${devicePath(id)}/phone/messages?unread=${unread}`);
export const getConversation = (id: string, threadId: string) =>
  api.get<{ messages: Message[] }>(`${devicePath(id)}/phone/messages/${encodeURIComponent(threadId)}`);
export const markThreadRead = (id: string, threadId: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/phone/messages/${encodeURIComponent(threadId)}/read`);
export const getCalls = (id: string, kind?: string) =>
  api.get<{ calls: Call[] }>(`${devicePath(id)}/phone/calls${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`);
export const getContacts = (id: string, search?: string) =>
  api.get<{ contacts: Contact[] }>(`${devicePath(id)}/phone/contacts${search ? `?search=${encodeURIComponent(search)}` : ""}`);
export const getCalendars = (id: string) => api.get<{ calendars: Calendar[] }>(`${devicePath(id)}/phone/calendars`);
export const getEvents = (id: string, days = 7) =>
  api.get<{ events: CalendarEvent[] }>(`${devicePath(id)}/phone/events?days=${days}`);

// -- files -----------------------------------------------------------------

export const listFiles = (id: string, path: string) =>
  api.get<FileList>(`${devicePath(id)}/files?path=${encodeURIComponent(path)}`);
export const fileDownloadUrl = (id: string, path: string) =>
  `${devicePath(id)}/files/download?path=${encodeURIComponent(path)}`;
export const pushFile = (id: string, local: string, remote: string) =>
  api.post<{ ok: boolean; detail: string }>(`${devicePath(id)}/files/push`, { local, remote });
export const pullFile = (id: string, remote: string, local: string) =>
  api.post<{ ok: boolean; detail: string }>(`${devicePath(id)}/files/pull`, { remote, local });
export const makeDir = (id: string, path: string) =>
  api.post<{ ok: boolean }>(`${devicePath(id)}/files/mkdir`, { path });
export const removeFile = (id: string, path: string) =>
  api.delete<{ ok: boolean }>(`${devicePath(id)}/files?path=${encodeURIComponent(path)}`);

// -- mirroring -------------------------------------------------------------

export const mirrorStatus = (id: string) =>
  api.get<{
    available: boolean;
    reason: string;
    server_version: string;
    mediamtx_version: string;
    provisioned: boolean;
    ffmpeg: string | null;
    active: boolean;
  }>(`${devicePath(id)}/mirror/status`);

export const startMirror = (id: string) =>
  api.post<{ path: string; whep: string; active: boolean }>(`${devicePath(id)}/mirror`);

export const stopMirror = (id: string) => api.delete<{ active: boolean }>(`${devicePath(id)}/mirror`);

export const mirrorWhep = async (id: string, offer: string): Promise<string> => {
  const response = await fetch(`${devicePath(id)}/mirror/whep`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/sdp" },
    body: offer,
  });
  const text = await response.text();
  if (!response.ok) {
    throw new Error(text || response.statusText);
  }
  return text;
};

// -- settings and system ---------------------------------------------------

export const getSettings = () => api.get<Settings>("/api/settings");
export const updateSettings = (patch: {
  reach?: string;
  port?: number;
  remote_domain?: string;
  flutter_path?: string;
  adb_path?: string;
}) =>
  api.patch<Settings>("/api/settings", patch);
export const rotateToken = () => api.post<{ token: string }>("/api/settings/token");
export const getDoctor = () => api.get<DoctorReport>("/api/system/doctor");
export const installTool = (tool: string) =>
  api.post<{ ok: boolean; requires_sudo?: boolean; command?: string; manual?: string; note?: string; output?: string }>(
    "/api/system/install",
    { tool },
  );

export const getTools = () => api.get<ToolsReport>("/api/system/tools");

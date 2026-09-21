import { api } from "./client";
import type {
  AuthState,
  Device,
  DeviceList,
  DiscoverResult,
  Project,
  Run,
  SystemInfo,
  Telemetry,
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
};

export const getAuth = () => api.get<AuthState>("/api/auth/me");
export const setupOwner = (password: string) => api.post<AuthState>("/api/setup", { password });
export const login = (password: string, remember: boolean) =>
  api.post<AuthState>("/api/auth/login", { password, remember });
export const logout = () => api.post<AuthState>("/api/auth/logout");

export const getSystem = () => api.get<SystemInfo>("/api/system");

export const listDevices = () => api.get<DeviceList>("/api/devices");
export const discoverDevices = () => api.post<DiscoverResult>("/api/devices/discover");
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

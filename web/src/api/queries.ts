import { api } from "./client";
import type { AuthState, Device, DeviceList, DiscoverResult, SystemInfo, Telemetry } from "./types";

export const keys = {
  auth: ["auth"] as const,
  devices: ["devices"] as const,
  device: (id: string) => ["device", id] as const,
  telemetry: (id: string) => ["telemetry", id] as const,
  system: ["system"] as const,
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

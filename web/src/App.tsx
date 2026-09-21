import { useQuery } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";

import { getAuth, keys } from "@/api/queries";
import { AppShell } from "@/components/AppShell";
import { Spinner } from "@/components/ui";
import { useDeviceEvents } from "@/hooks/useDeviceEvents";
import { DashboardPage } from "@/pages/Dashboard";
import { DeviceDetailPage } from "@/pages/DeviceDetail";
import { DevicesPage } from "@/pages/Devices";
import { LoginPage } from "@/pages/Login";
import { ProjectDetailPage } from "@/pages/ProjectDetail";
import { ProjectsPage } from "@/pages/Projects";
import { RunPage } from "@/pages/Run";
import { RunsPage } from "@/pages/Runs";
import { SettingsPage } from "@/pages/Settings";
import { SetupPage } from "@/pages/Setup";
import { SystemPage } from "@/pages/System";

export default function App() {
  const auth = useQuery({ queryKey: keys.auth, queryFn: getAuth });
  useDeviceEvents(Boolean(auth.data?.authenticated));

  if (auth.isLoading) {
    return (
      <div className="grid min-h-full place-items-center">
        <Spinner label="Starting Fenox" />
      </div>
    );
  }
  if (auth.error) {
    return (
      <div className="grid min-h-full place-items-center p-6 text-sm text-red-400">
        Cannot reach the Fenox hub.
      </div>
    );
  }
  if (!auth.data?.configured) {
    return <SetupPage />;
  }
  if (!auth.data.authenticated) {
    return <LoginPage />;
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="devices" element={<DevicesPage />} />
        <Route path="devices/:id" element={<DeviceDetailPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:name" element={<ProjectDetailPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:id" element={<RunPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

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
import { SetupPage } from "@/pages/Setup";

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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

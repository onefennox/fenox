import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { keys } from "@/api/queries";
import type { Device, DeviceEvent, DeviceList } from "@/api/types";

/**
 * Subscribe to the hub's device event stream and keep the devices query in sync.
 * Reconnects with a short backoff while the app is mounted.
 */
export function useDeviceEvents(enabled: boolean): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    let socket: WebSocket | null = null;
    let stopped = false;
    let reconnect: number | undefined;

    const apply = (data: DeviceEvent) => {
      if (data.type !== "devices") {
        return;
      }
      queryClient.setQueryData<DeviceList>(keys.devices, (previous) => {
        const disabled = new Map<string, boolean>(
          (previous?.devices ?? []).map((device) => [device.id, device.disabled]),
        );
        const devices: Device[] = data.devices.map((device) => ({
          ...device,
          disabled: disabled.get(device.id) ?? false,
        }));
        return { devices, pending: data.pending };
      });
    };

    const connect = () => {
      socket = new WebSocket(`${protocol}://${window.location.host}/ws/events`);
      socket.onmessage = (event) => {
        try {
          apply(JSON.parse(event.data) as DeviceEvent);
        } catch {
          // Ignore frames we cannot parse; the next tick will resend state.
        }
      };
      socket.onclose = () => {
        if (!stopped) {
          reconnect = window.setTimeout(connect, 2000);
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (reconnect) {
        window.clearTimeout(reconnect);
      }
      socket?.close();
    };
  }, [enabled, queryClient]);
}

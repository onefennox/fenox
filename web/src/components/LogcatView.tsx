import { useEffect, useRef } from "react";

/** Live `adb logcat` for one device, streamed over a WebSocket. */
export function LogcatView({ deviceId }: { deviceId: string }) {
  const container = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) {
      return;
    }
    element.textContent = "";
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/logcat/${encodeURIComponent(deviceId)}`);
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as { type: string; line?: string; detail?: string };
        if (message.type === "log" && message.line !== undefined) {
          element.textContent += `${message.line}\n`;
          element.scrollTop = element.scrollHeight;
        } else if (message.type === "error") {
          element.textContent += `${message.detail}\n`;
        }
      } catch {
        // Ignore unparseable frames.
      }
    };
    return () => socket.close();
  }, [deviceId]);

  return (
    <pre
      ref={container}
      className="h-72 overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2 font-mono text-xs text-[var(--color-muted)]"
    />
  );
}

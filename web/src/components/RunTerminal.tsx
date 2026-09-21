import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef } from "react";

import type { Run } from "@/api/types";

interface RunTerminalProps {
  runId: string;
  onStatus?: (run: Partial<Run> & { type?: string }) => void;
}

/**
 * Live `flutter run` output. Output is streamed from the hub over a WebSocket;
 * reload and restart are driven by the control buttons, not by typing here.
 */
export function RunTerminal({ runId, onStatus }: RunTerminalProps) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = container.current;
    if (!element) {
      return;
    }
    const term = new Terminal({
      convertEol: true,
      fontSize: 12,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      scrollback: 5000,
      theme: {
        background: "#0b0d12",
        foreground: "#e6e9ef",
        cursor: "#4f8cff",
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(element);
    fit.fit();

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/runs/${encodeURIComponent(runId)}`);
    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as { type: string; line?: string };
        if (message.type === "log" && message.line !== undefined) {
          term.write(`${message.line}\r\n`);
        } else if (message.type === "status" || message.type === "exit") {
          onStatus?.(message as Partial<Run> & { type?: string });
        }
      } catch {
        // Ignore frames we cannot parse.
      }
    };
    socket.onclose = () => term.write("\r\n\x1b[2m[stream disconnected]\x1b[0m\r\n");

    const resize = () => fit.fit();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      socket.close();
      term.dispose();
    };
  }, [runId, onStatus]);

  return <div ref={container} className="h-full w-full overflow-hidden" />;
}

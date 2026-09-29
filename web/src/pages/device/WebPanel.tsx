import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, Globe, Monitor, RefreshCw, Smartphone, Tablet } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { getBrowser, keys } from "@/api/queries";
import { Button, Card, ErrorText, Input } from "@/components/ui";

const DEVICE_ICONS: Record<string, React.ReactNode> = {
  desktop: <Monitor size={14} />,
  laptop: <Monitor size={14} />,
  tablet: <Tablet size={14} />,
  mobile: <Smartphone size={14} />,
};

/**
 * A real browser, shown in the page.
 *
 * The frames come from a Chrome the hub runs and drives over the DevTools
 * Protocol, not from an iframe. That is what makes every site work: nothing is
 * embedded, so no site can refuse to be framed, and switching between desktop,
 * tablet and mobile changes the actual viewport, pixel ratio and touch flag —
 * so the site serves the layout it would serve that device.
 *
 * Coordinates map 1:1 because the stream is sized to the emulated viewport, so a
 * point on the canvas is the same point in the page.
 */
export function WebPanel() {
  const status = useQuery({ queryKey: keys.browser, queryFn: getBrowser });
  const canvas = useRef<HTMLCanvasElement>(null);
  const socket = useRef<WebSocket | null>(null);
  const [url, setUrl] = useState("");
  const [input, setInput] = useState("");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [size, setSize] = useState({ width: 0, height: 0 });

  const send = useCallback((message: Record<string, unknown>) => {
    if (socket.current?.readyState === WebSocket.OPEN) {
      socket.current.send(JSON.stringify(message));
    }
  }, []);

  useEffect(() => {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/browser`);
    ws.binaryType = "blob";
    socket.current = ws;

    ws.onmessage = async (event) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data);
        if (message.type === "error") setError(message.message);
        return;
      }
      // A frame. Decoded off the main thread, then painted.
      const bitmap = await createImageBitmap(event.data as Blob);
      const target = canvas.current;
      if (target) {
        if (target.width !== bitmap.width || target.height !== bitmap.height) {
          target.width = bitmap.width;
          target.height = bitmap.height;
          setSize({ width: bitmap.width, height: bitmap.height });
        }
        target.getContext("2d")?.drawImage(bitmap, 0, 0);
      }
      bitmap.close();
      setReady(true);
    };
    ws.onerror = () => setError("Could not reach the browser stream.");
    return () => ws.close();
  }, []);

  // Tell the server which device to emulate; it reloads so the layout is real.
  const changeDevice = (next: string) => {
    send({ t: "device", v: next });
    status.refetch();
  };

  const point = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    // The frame is the emulated viewport, so this is a direct proportion.
    return {
      x: ((event.clientX - rect.left) / rect.width) * size.width,
      y: ((event.clientY - rect.top) / rect.height) * size.height,
    };
  };

  const current = status.data?.device ?? "desktop";

  return (
    <div className="space-y-3">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          send({ t: "navigate", v: input });
          setUrl(input);
        }}
      >
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="control-center.paylesa.com"
          aria-label="Address"
          spellCheck={false}
          autoComplete="off"
          className="min-w-48 flex-1"
        />
        <Button type="submit" className="shrink-0">
          <Globe size={14} />
          Go
        </Button>
        <Button type="button" variant="ghost" title="Back" className="shrink-0" onClick={() => send({ t: "back" })}>
          <ArrowLeft size={14} />
        </Button>
        <Button type="button" variant="ghost" title="Reload" className="shrink-0" onClick={() => send({ t: "reload" })}>
          <RefreshCw size={14} />
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-1.5">
        {status.data?.devices.map((entry) => (
          <Button
            key={entry.id}
            type="button"
            variant={current === entry.id ? "primary" : "secondary"}
            className="shrink-0"
            onClick={() => changeDevice(entry.id)}
            title={`${entry.width}×${entry.height}`}
          >
            {DEVICE_ICONS[entry.id]}
            {entry.label}
          </Button>
        ))}
        <span className="ml-1 text-xs text-[var(--color-muted)]">
          {size.width ? `${size.width}×${size.height}` : ""}
        </span>
        {url ? (
          <Button
            type="button"
            variant="ghost"
            className="ml-auto shrink-0"
            onClick={() => window.open(url.startsWith("http") ? url : `https://${url}`, "_blank", "noopener,noreferrer")}
          >
            <ExternalLink size={14} />
            Open in a tab
          </Button>
        ) : null}
      </div>

      {error ? <ErrorText>{error}</ErrorText> : null}
      {status.data && !status.data.available ? (
        <ErrorText>
          No Chrome or Chromium was found on the machine running Fenox. Install one to use this tab.
        </ErrorText>
      ) : null}

      <div
        className="overflow-hidden rounded-xl border border-[var(--color-border)] bg-white"
        // Typing goes to the page rather than the dashboard; only printable keys
        // and a few controls are forwarded.
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "Backspace" || event.key === "Tab") {
            event.preventDefault();
            send({ t: "key", v: event.key });
          } else if (event.key.length === 1 && !event.metaKey && !event.ctrlKey) {
            send({ t: "text", v: event.key });
          }
        }}
      >
        <canvas
          ref={canvas}
          className="block w-full cursor-pointer bg-white"
          style={{ maxHeight: "70vh", objectFit: "contain" }}
          onClick={(event) => {
            const { x, y } = point(event);
            send({ t: "click", x, y });
          }}
          onWheel={(event) => {
            const { x, y } = point(event);
            send({ t: "scroll", x, y, dy: event.deltaY, dx: event.deltaX });
          }}
        />
        {!ready ? (
          <Card className="border-0 p-8 text-center text-sm text-[var(--color-muted)]">
            <Globe size={20} className="mx-auto mb-3 opacity-60" />
            Starting a browser…
            <div className="mt-2 text-xs">Type an address above. First start takes a few seconds.</div>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

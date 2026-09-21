import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { keys, mirrorStatus, sendInput } from "@/api/queries";
import type { Device } from "@/api/types";
import { Button, Card, ErrorText, Spinner } from "@/components/ui";

type Phase = "idle" | "connecting" | "live" | "error";

/** The H.264 codec string for a WebCodecs decoder, read from the stream's SPS. */
function codecString(nal: Uint8Array): string {
  let index = 0;
  while (index + 4 < nal.length) {
    if (nal[index] === 0 && nal[index + 1] === 0 && nal[index + 2] === 1) {
      const nalType = nal[index + 3] & 0x1f;
      if (nalType === 7 && index + 7 < nal.length) {
        const profile = nal[index + 4];
        const constraints = nal[index + 5];
        const level = nal[index + 6];
        const hex = (value: number) => value.toString(16).padStart(2, "0");
        return `avc1.${hex(profile)}${hex(constraints)}${hex(level)}`;
      }
      index += 3;
    } else {
      index += 1;
    }
  }
  return "avc1.42E01E";
}

function isKeyframe(nal: Uint8Array): boolean {
  for (let index = 0; index + 4 < nal.length; index += 1) {
    if (nal[index] === 0 && nal[index + 1] === 0 && nal[index + 2] === 1 && (nal[index + 3] & 0x1f) === 5) {
      return true;
    }
  }
  return false;
}

export function MirrorPanel({ device }: { device: Device }) {
  const status = useQuery({ queryKey: [...keys.info(device.id), "mirror"], queryFn: () => mirrorStatus(device.id) });
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const decoderRef = useRef<{ configure: (c: unknown) => void; decode: (c: unknown) => void; close: () => void } | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const pointerRef = useRef<{ x: number; y: number } | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");

  useEffect(() => () => socketRef.current?.close(), []);

  if (!device.online) {
    return <Card className="p-6 text-sm text-[var(--color-muted)]">The device is offline.</Card>;
  }
  if (status.isLoading) {
    return <Spinner label="Checking mirroring support" />;
  }
  if (status.data && !status.data.available) {
    return (
      <Card className="p-6 text-sm text-amber-300">
        Mirroring is unavailable: {status.data.reason}. Install scrcpy and reload.
      </Card>
    );
  }

  const toDevice = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !sizeRef.current.width) {
      return { x: 0, y: 0 };
    }
    const rect = canvas.getBoundingClientRect();
    return {
      x: Math.round(((event.clientX - rect.left) / rect.width) * sizeRef.current.width),
      y: Math.round(((event.clientY - rect.top) / rect.height) * sizeRef.current.height),
    };
  };

  const start = () => {
    setError("");
    setPhase("connecting");
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/mirror/${encodeURIComponent(device.id)}`);
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;

    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        const message = JSON.parse(event.data) as { type: string; detail?: string; width?: number; height?: number };
        if (message.type === "error") {
          setError(message.detail ?? "mirroring failed");
          setPhase("error");
          socket.close();
        } else if (message.type === "meta") {
          sizeRef.current = { width: message.width ?? 0, height: message.height ?? 0 };
          const canvas = canvasRef.current;
          if (canvas) {
            canvas.width = message.width ?? 0;
            canvas.height = message.height ?? 0;
          }
          setPhase("live");
        }
        return;
      }
      const Decoder = (globalThis as unknown as { VideoDecoder?: new (init: unknown) => never }).VideoDecoder;
      if (!Decoder) {
        setError("This browser does not support WebCodecs video decoding.");
        setPhase("error");
        return;
      }
      const bytes = new Uint8Array(event.data as ArrayBuffer);
      if (bytes.length <= 12) {
        return;
      }
      const payload = bytes.subarray(12);
      const view = new DataView(event.data as ArrayBuffer);
      const timestamp = Number(view.getBigUint64(0));
      if (!decoderRef.current) {
        const decoder = new Decoder({
          output: (frame: { close: () => void }) => {
            const canvas = canvasRef.current;
            const context = canvas?.getContext("2d");
            if (canvas && context) {
              context.drawImage(frame as unknown as CanvasImageSource, 0, 0, canvas.width, canvas.height);
            }
            frame.close();
          },
          error: (err: Error) => {
            setError(err.message);
            setPhase("error");
          },
        }) as unknown as { configure: (c: unknown) => void; decode: (c: unknown) => void; close: () => void };
        decoder.configure({ codec: codecString(payload), optimizeForLatency: true, avc: { format: "annexb" } });
        decoderRef.current = decoder;
      }
      const Chunk = (globalThis as unknown as {
        EncodedVideoChunk: new (init: unknown) => never;
      }).EncodedVideoChunk;
      decoderRef.current.decode(
        new Chunk({ type: isKeyframe(payload) ? "key" : "delta", timestamp, data: payload.slice() }),
      );
    };

    socket.onclose = () => {
      decoderRef.current?.close();
      decoderRef.current = null;
      setPhase((current) => (current === "error" ? current : "idle"));
    };
  };

  const stop = () => {
    socketRef.current?.close();
    socketRef.current = null;
  };

  const tapDevice = (x: number, y: number) => sendInput(device.id, { type: "tap", x, y }).catch(() => undefined);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {phase === "idle" || phase === "error" ? (
          <Button onClick={start}>Start mirroring</Button>
        ) : (
          <Button variant="danger" onClick={stop}>
            Stop
          </Button>
        )}
        {phase === "connecting" ? <span className="text-sm text-[var(--color-muted)]">Starting scrcpy…</span> : null}
        {phase === "live" ? <span className="text-sm text-emerald-400">Live</span> : null}
        <div className="ml-auto flex gap-1">
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "BACK" })}>
            Back
          </Button>
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "HOME" })}>
            Home
          </Button>
          <Button variant="ghost" onClick={() => sendInput(device.id, { type: "key", key: "APP_SWITCH" })}>
            Recents
          </Button>
        </div>
      </div>
      <ErrorText>{error}</ErrorText>

      <Card className="grid place-items-center p-2">
        <canvas
          ref={canvasRef}
          className="max-h-[70vh] w-auto max-w-full touch-none rounded-md bg-black"
          onPointerDown={(event) => {
            pointerRef.current = toDevice(event);
          }}
          onPointerUp={(event) => {
            const start = pointerRef.current;
            pointerRef.current = null;
            const end = toDevice(event);
            if (!start) {
              return;
            }
            const distance = Math.abs(end.x - start.x) + Math.abs(end.y - start.y);
            if (distance < 24) {
              tapDevice(end.x, end.y);
            } else {
              sendInput(device.id, { type: "swipe", x: start.x, y: start.y, x2: end.x, y2: end.y, duration: 200 }).catch(
                () => undefined,
              );
            }
          }}
        />
        {phase !== "live" ? (
          <p className="p-8 text-sm text-[var(--color-muted)]">
            {status.data?.available ? "Start mirroring to see and control the screen." : "Mirroring is unavailable."}
          </p>
        ) : null}
      </Card>
    </div>
  );
}

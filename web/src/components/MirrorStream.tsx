import { ScrcpyOptions3_3_3 } from "@yume-chan/scrcpy";
import { BitmapVideoFrameRenderer, WebCodecsVideoDecoder, WebGLVideoFrameRenderer } from "@yume-chan/scrcpy-decoder-webcodecs";
import { useEffect, useRef } from "react";

import { sendInput } from "@/api/queries";

export type MirrorPhase = "connecting" | "live" | "error";

interface MirrorStreamProps {
  deviceId: string;
  /** Map pointer taps and swipes to device input. */
  interactive?: boolean;
  className?: string;
  onPhaseChange?: (phase: MirrorPhase) => void;
  onError?: (message: string) => void;
  onSizeChange?: (width: number, height: number) => void;
}

// Must match the options the hub uses to start the server.
const options = new ScrcpyOptions3_3_3({ audio: false, control: false });

/**
 * Live scrcpy video.
 *
 * The hub proxies the raw video socket; the Tango scrcpy client parses the
 * device metadata and frame packets, and the WebCodecs decoder renders H.264 to
 * a canvas. Input goes back through the device action endpoints.
 */
export function MirrorStream({
  deviceId,
  interactive = true,
  className = "",
  onPhaseChange,
  onError,
  onSizeChange,
}: MirrorStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const size = useRef({ width: 0, height: 0 });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    onPhaseChange?.("connecting");
    let cancelled = false;
    let decoder: WebCodecsVideoDecoder | null = null;
    let controller: ReadableStreamDefaultController<Uint8Array> | null = null;

    const fail = (message: string) => {
      if (cancelled) return;
      onPhaseChange?.("error");
      onError?.(message);
    };

    if (!WebCodecsVideoDecoder.isSupported) {
      fail("This browser does not support WebCodecs video decoding.");
      return;
    }

    const readable = new ReadableStream<Uint8Array>({
      start(value) {
        controller = value;
      },
    });

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/mirror/${encodeURIComponent(deviceId)}`);
    socket.binaryType = "arraybuffer";
    socket.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          const message = JSON.parse(event.data) as { type?: string; detail?: string };
          if (message.type === "error") {
            fail(message.detail ?? "Mirroring could not start.");
            socket.close();
          }
        } catch {
          // Ignore frames we cannot parse.
        }
        return;
      }
      controller?.enqueue(new Uint8Array(event.data as ArrayBuffer));
    };
    socket.onclose = () => {
      try {
        controller?.close();
      } catch {
        // Already closed.
      }
    };
    socket.onerror = () => fail("Could not open the mirror connection.");

    void (async () => {
      try {
        const parsed = await options.parseVideoStreamMetadata(
          readable as unknown as Parameters<typeof options.parseVideoStreamMetadata>[0],
        );
        if (cancelled) return;
        size.current = { width: parsed.metadata.width ?? 0, height: parsed.metadata.height ?? 0 };
        if (size.current.width && size.current.height) {
          onSizeChange?.(size.current.width, size.current.height);
        }

        const renderer = WebGLVideoFrameRenderer.isSupported ? new WebGLVideoFrameRenderer() : new BitmapVideoFrameRenderer();
        decoder = new WebCodecsVideoDecoder({ codec: parsed.metadata.codec, renderer });
        decoder.sizeChanged(({ width, height }) => {
          size.current = { width, height };
          onSizeChange?.(width, height);
        });

        const canvas = renderer.canvas as HTMLCanvasElement;
        canvas.className = `block max-h-full max-w-full ${className}`;
        attachPointer(canvas, deviceId, size, interactive);
        container.replaceChildren(canvas);
        onPhaseChange?.("live");
        await parsed.stream.pipeThrough(options.createMediaStreamTransformer()).pipeTo(decoder.writable);
      } catch (error) {
        fail(error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      cancelled = true;
      socket.close();
      try {
        decoder?.dispose();
      } catch {
        // Decoder may already be closed.
      }
      container.replaceChildren();
    };
  }, [deviceId, interactive, onError, onPhaseChange, onSizeChange]);

  return <div ref={containerRef} className="grid h-full w-full place-items-center" />;
}

function attachPointer(
  element: HTMLElement,
  deviceId: string,
  size: { current: { width: number; height: number } },
  interactive: boolean,
): void {
  if (!interactive) {
    return;
  }
  let start: { x: number; y: number } | null = null;

  const toDevice = (event: PointerEvent) => {
    const rect = element.getBoundingClientRect();
    const width = size.current.width || rect.width;
    const height = size.current.height || rect.height;
    return {
      x: Math.round(((event.clientX - rect.left) / rect.width) * width),
      y: Math.round(((event.clientY - rect.top) / rect.height) * height),
    };
  };

  element.style.touchAction = "none";
  element.addEventListener("pointerdown", (event) => {
    start = toDevice(event);
  });
  element.addEventListener("pointerup", (event) => {
    const from = start;
    start = null;
    if (!from) return;
    const to = toDevice(event);
    const distance = Math.abs(to.x - from.x) + Math.abs(to.y - from.y);
    if (distance < 24) {
      void sendInput(deviceId, { type: "tap", x: to.x, y: to.y }).catch(() => undefined);
    } else {
      void sendInput(deviceId, { type: "swipe", x: from.x, y: from.y, x2: to.x, y2: to.y, duration: 200 }).catch(
        () => undefined,
      );
    }
  });
}

import { useEffect, useRef } from "react";

import { sendInput, startMirror, stopMirror } from "@/api/queries";

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

/**
 * Live mirror over Media Source Extensions.
 *
 * The hub remuxes the device's H.264 to fragmented MP4 and streams it over the
 * same WebSocket the app already uses; the browser's own media stack decodes and
 * plays it in a native <video>. No WebRTC, no extra ports, and nothing to
 * negotiate — so it works wherever the app itself works.
 */
export function MirrorStream({
  deviceId,
  interactive = true,
  className = "",
  onPhaseChange,
  onError,
  onSizeChange,
}: MirrorStreamProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let mediaSource: MediaSource | null = null;
    let sourceBuffer: SourceBuffer | null = null;
    let objectUrl: string | null = null;
    const queue: ArrayBuffer[] = [];
    const video = videoRef.current;

    const fail = (message: string) => {
      if (cancelled) return;
      onPhaseChange?.("error");
      onError?.(message);
    };

    const appendNext = () => {
      if (!sourceBuffer || sourceBuffer.updating || queue.length === 0) {
        return;
      }
      try {
        sourceBuffer.appendBuffer(queue.shift() as ArrayBuffer);
      } catch (error) {
        fail(error instanceof Error ? error.message : String(error));
      }
    };

    const trimBuffer = () => {
      if (!sourceBuffer || !video || sourceBuffer.updating) {
        return;
      }
      const behind = video.currentTime - 0.6;
      if (behind > 0 && sourceBuffer.buffered.length > 0 && sourceBuffer.buffered.start(0) < behind) {
        try {
          sourceBuffer.remove(0, behind);
        } catch {
          // Removal is best-effort.
        }
      }
    };

    const setup = (codec: string) => {
      if (!video || mediaSource || cancelled) {
        return;
      }
      const mime = `video/mp4; codecs="${codec}"`;
      mediaSource = new MediaSource();
      objectUrl = URL.createObjectURL(mediaSource);
      video.src = objectUrl;
      mediaSource.addEventListener("sourceopen", () => {
        if (!mediaSource) return;
        try {
          sourceBuffer = mediaSource.addSourceBuffer(mime);
          sourceBuffer.mode = "segments";
          sourceBuffer.addEventListener("updateend", () => {
            appendNext();
            trimBuffer();
            void video.play().catch(() => undefined);
          });
          appendNext();
        } catch (error) {
          fail(error instanceof Error ? error.message : String(error));
        }
      });
    };

    void (async () => {
      try {
        onPhaseChange?.("connecting");
        const started = await startMirror(deviceId);
        if (cancelled) return;
        setup(started.codec);

        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${protocol}://${window.location.host}/ws/mirror/${encodeURIComponent(deviceId)}`);
        socket.binaryType = "arraybuffer";
        socket.onmessage = (event) => {
          if (typeof event.data === "string") {
            try {
              const message = JSON.parse(event.data) as { type?: string; codec?: string; detail?: string };
              if (message.type === "error") {
                fail(message.detail ?? "Mirroring could not start.");
              } else if (message.type === "codec" && message.codec) {
                onPhaseChange?.("live");
              }
            } catch {
              // Ignore frames we cannot parse.
            }
            return;
          }
          queue.push(event.data as ArrayBuffer);
          appendNext();
        };
        socket.onerror = () => fail("Could not open the mirror connection.");
      } catch (error) {
        fail(error instanceof Error ? error.message : String(error));
      }
    })();

    if (video) {
      video.onloadedmetadata = () => {
        onSizeChange?.(video.videoWidth, video.videoHeight);
        attachPointer(video, deviceId, interactive);
      };
    }

    return () => {
      cancelled = true;
      socket?.close();
      if (sourceBuffer && mediaSource && mediaSource.readyState === "open") {
        try {
          mediaSource.endOfStream();
        } catch {
          // Already closing.
        }
      }
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
      if (video) {
        video.src = "";
      }
      void stopMirror(deviceId).catch(() => undefined);
    };
  }, [deviceId, interactive, onError, onPhaseChange, onSizeChange]);

  return <video ref={videoRef} autoPlay playsInline muted className={className} />;
}

function attachPointer(video: HTMLVideoElement, deviceId: string, interactive: boolean): void {
  if (!interactive) {
    return;
  }
  let start: { x: number; y: number } | null = null;

  const toDevice = (event: PointerEvent) => {
    const rect = video.getBoundingClientRect();
    const width = video.videoWidth || rect.width;
    const height = video.videoHeight || rect.height;
    return {
      x: Math.round(((event.clientX - rect.left) / rect.width) * width),
      y: Math.round(((event.clientY - rect.top) / rect.height) * height),
    };
  };

  video.style.touchAction = "none";
  video.addEventListener("pointerdown", (event) => {
    start = toDevice(event);
  });
  video.addEventListener("pointerup", (event) => {
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

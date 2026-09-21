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
  // Parent renders commonly pass inline callbacks (notably onSizeChange). Their
  // identities change whenever the phase or aspect ratio changes, but that must
  // not tear down and restart the scrcpy session. Keep the latest handlers in
  // refs so only a device/interaction change owns the stream lifecycle.
  const onPhaseChangeRef = useRef(onPhaseChange);
  const onErrorRef = useRef(onError);
  const onSizeChangeRef = useRef(onSizeChange);
  onPhaseChangeRef.current = onPhaseChange;
  onErrorRef.current = onError;
  onSizeChangeRef.current = onSizeChange;

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
      onPhaseChangeRef.current?.("error");
      onErrorRef.current?.(message);
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

    const trimBuffer = (): boolean => {
      if (!sourceBuffer || !video || sourceBuffer.updating) {
        return false;
      }
      const buffered = sourceBuffer.buffered;
      if (buffered.length === 0) return false;

      // A live mirror must prefer the newest frame over smooth delayed
      // playback. MSE otherwise happily plays every queued frame and can drift
      // seconds behind the phone after a short CPU/network stall.
      const liveEdge = buffered.end(buffered.length - 1);
      if (liveEdge - video.currentTime > 0.75) {
        video.currentTime = Math.max(buffered.start(0), liveEdge - 0.1);
      }
      const behind = video.currentTime - 0.6;
      if (behind > 0 && buffered.start(0) < behind) {
        try {
          sourceBuffer.remove(0, behind);
          return true;
        } catch {
          // Removal is best-effort.
        }
      }
      return false;
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
            // remove() and appendBuffer() cannot overlap. Trim first and let
            // its own updateend continue the queue when removal was needed.
            if (!trimBuffer()) appendNext();
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
        onPhaseChangeRef.current?.("connecting");
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
      video.onplaying = () => onPhaseChangeRef.current?.("live");
      video.onloadedmetadata = () => {
        onSizeChangeRef.current?.(video.videoWidth, video.videoHeight);
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
  }, [deviceId, interactive]);

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

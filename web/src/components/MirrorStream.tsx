import { useEffect, useRef } from "react";

import { mirrorWhep, sendInput, startMirror, stopMirror } from "@/api/queries";

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

/** Wait for ICE gathering so the offer already carries its candidates. */
function waitForCandidates(peer: RTCPeerConnection, timeout = 2500): Promise<void> {
  if (peer.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const finish = () => {
      peer.removeEventListener("icegatheringstatechange", onChange);
      resolve();
    };
    const onChange = () => {
      if (peer.iceGatheringState === "complete") {
        finish();
      }
    };
    peer.addEventListener("icegatheringstatechange", onChange);
    window.setTimeout(finish, timeout);
  });
}

/**
 * Live mirror over WebRTC.
 *
 * The hub publishes the device's H.264 to MediaMTX; the browser negotiates a
 * WHEP session through the hub and plays it in a plain <video>, so the browser's
 * own media stack handles decoding, buffering and reconnection.
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
    let peer: RTCPeerConnection | null = null;

    const fail = (message: string) => {
      if (cancelled) return;
      onPhaseChange?.("error");
      onError?.(message);
    };

    void (async () => {
      try {
        onPhaseChange?.("connecting");
        await startMirror(deviceId);
        if (cancelled) return;

        peer = new RTCPeerConnection();
        peer.addTransceiver("video", { direction: "recvonly" });
        peer.ontrack = (event) => {
          const video = videoRef.current;
          if (video && event.streams[0]) {
            video.srcObject = event.streams[0];
          }
        };
        peer.onconnectionstatechange = () => {
          if (!peer) return;
          if (peer.connectionState === "connected") {
            onPhaseChange?.("live");
          } else if (peer.connectionState === "failed") {
            fail("The WebRTC connection failed.");
          }
        };

        const video = videoRef.current;
        if (video) {
          video.onloadedmetadata = () => {
            onSizeChange?.(video.videoWidth, video.videoHeight);
            attachPointer(video, deviceId, interactive);
          };
        }

        const offer = await peer.createOffer();
        await peer.setLocalDescription(offer);
        await waitForCandidates(peer);
        if (cancelled || !peer.localDescription) return;

        const answer = await mirrorWhep(deviceId, peer.localDescription.sdp);
        await peer.setRemoteDescription({ type: "answer", sdp: answer });
      } catch (error) {
        fail(error instanceof Error ? error.message : String(error));
      }
    })();

    return () => {
      cancelled = true;
      peer?.close();
      void stopMirror(deviceId).catch(() => undefined);
      const video = videoRef.current;
      if (video) {
        video.srcObject = null;
      }
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

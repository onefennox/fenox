import { Power } from "lucide-react";
import type { ReactNode } from "react";

interface PhoneFrameProps {
  /** The screen is on. When false the phone reads as powered off (black). */
  power: boolean;
  /** Screen aspect ratio (width / height). Defaults to a modern phone. */
  aspect?: number;
  children?: ReactNode;
  className?: string;
  /** Maximum width in pixels; the frame scales down to fit. */
  maxWidth?: number;
}

/**
 * A realistic phone body: rounded shell, bezel, side buttons, a camera island,
 * and a subtle glass reflection. The screen area holds whatever is passed in —
 * the live mirror when on, otherwise a powered-off screen.
 */
export function PhoneFrame({ power, aspect = 9 / 19.5, children, className = "", maxWidth = 230 }: PhoneFrameProps) {
  return (
    <div className={`relative mx-auto w-full ${className}`} style={{ maxWidth }}>
      {/* side buttons */}
      <span className="absolute -left-[3px] top-[16%] h-8 w-[3px] rounded-l-sm bg-neutral-600" />
      <span className="absolute -left-[3px] top-[26%] h-14 w-[3px] rounded-l-sm bg-neutral-600" />
      <span className="absolute -right-[3px] top-[22%] h-16 w-[3px] rounded-r-sm bg-neutral-600" />

      {/* body */}
      <div className="relative rounded-[2.4rem] bg-gradient-to-b from-neutral-700 via-neutral-800 to-neutral-900 p-[10px] shadow-[0_18px_40px_-12px_rgba(0,0,0,0.9)] ring-1 ring-black/70">
        {/* inner bezel */}
        <div className="rounded-[1.9rem] bg-black p-[3px] ring-1 ring-white/5">
          <div className="relative overflow-hidden rounded-[1.7rem] bg-black" style={{ aspectRatio: String(aspect) }}>
            {/* camera island */}
            <span className="absolute left-1/2 top-2 z-20 h-[16px] w-[70px] -translate-x-1/2 rounded-full bg-black ring-1 ring-white/10">
              <span className="absolute right-2 top-1/2 h-[6px] w-[6px] -translate-y-1/2 rounded-full bg-neutral-700" />
            </span>

            {/* screen content */}
            <div className="absolute inset-0 grid place-items-center overflow-hidden">
              {power ? (
                children
              ) : (
                <div className="flex flex-col items-center gap-2 text-neutral-700">
                  <Power size={22} />
                  <span className="text-[10px] tracking-wide uppercase">Off</span>
                </div>
              )}
            </div>

            {/* glass reflection */}
            <span
              className="pointer-events-none absolute inset-0 z-10"
              style={{ background: "linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0) 38%)" }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

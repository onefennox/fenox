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
  /** A thinner bezel, for a larger screen in the same space. */
  slim?: boolean;
}

/**
 * A realistic phone body: rounded shell, bezel, side buttons, a camera island,
 * and a subtle glass reflection. The screen area holds whatever is passed in —
 * the live mirror when on, otherwise a powered-off screen.
 */
export function PhoneFrame({ power, aspect = 9 / 19.5, children, className = "", maxWidth = 230, slim = false }: PhoneFrameProps) {
  return (
    <div className={`relative mx-auto w-full ${className}`} style={{ maxWidth }}>
      {/* side buttons */}
      {slim ? null : (
        <>
          <span className="absolute -left-[3px] top-[16%] h-8 w-[3px] rounded-l-sm bg-neutral-600" />
          <span className="absolute -left-[3px] top-[26%] h-14 w-[3px] rounded-l-sm bg-neutral-600" />
          <span className="absolute -right-[3px] top-[22%] h-16 w-[3px] rounded-r-sm bg-neutral-600" />
        </>
      )}

      {/* body */}
      <div className={`relative bg-gradient-to-b from-neutral-700 via-neutral-800 to-neutral-900 shadow-[0_18px_40px_-12px_rgba(0,0,0,0.9)] ring-1 ring-black/70 ${slim ? "rounded-[2rem] p-[6px]" : "rounded-[2.4rem] p-[10px]"}`}>
        {/* inner bezel */}
        <div className={`bg-black ring-1 ring-white/5 ${slim ? "rounded-[1.7rem] p-[2px]" : "rounded-[1.9rem] p-[3px]"}`}>
          <div className={`relative overflow-hidden bg-black ${slim ? "rounded-[1.6rem]" : "rounded-[1.7rem]"}`} style={{ aspectRatio: String(aspect) }}>
            {/* camera island */}
            <span className={`absolute left-1/2 z-20 -translate-x-1/2 rounded-full bg-black ring-1 ring-white/10 ${slim ? "top-1.5 h-[12px] w-[54px]" : "top-2 h-[16px] w-[70px]"}`}>
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

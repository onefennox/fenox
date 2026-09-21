import { createContext, useContext } from "react";

/** Whether the live event stream to the hub is currently connected. */
export const LiveContext = createContext(false);

export function useLive(): boolean {
  return useContext(LiveContext);
}

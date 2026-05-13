import { useSamantha } from "./store";
import type { ScreenName } from "./types";

export function useRoute() {
  const setScreen = useSamantha((s) => s.setScreen);
  return (target: ScreenName) => setScreen(target);
}

export function useScreen(): ScreenName {
  return useSamantha((s) => s.screen);
}

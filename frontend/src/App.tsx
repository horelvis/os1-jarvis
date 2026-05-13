import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import { useScreen } from "./core/router";
import { AmbientScreen } from "./screens/AmbientScreen";
import { BootScreen } from "./screens/BootScreen";
import { ConversationScreen } from "./screens/ConversationScreen";
import { OnboardingScreen } from "./screens/OnboardingScreen";

export default function App() {
  const screen = useScreen();
  switch (screen) {
    case "boot":         return <BootScreen />;
    case "onboarding":   return <OnboardingScreen />;
    case "ambient":      return <AmbientScreen />;
    case "conversation": return <ConversationScreen />;
  }
}

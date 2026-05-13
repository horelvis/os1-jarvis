import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import { useScreen } from "./core/router";
import { BootScreen } from "./screens/BootScreen";

function Placeholder({ label }: { label: string }) {
  return (
    <div className="screen">
      <div className="label">{label} (placeholder)</div>
    </div>
  );
}

export default function App() {
  const screen = useScreen();
  switch (screen) {
    case "boot":         return <BootScreen />;
    case "onboarding":   return <Placeholder label="onboarding" />;
    case "ambient":      return <Placeholder label="ambient" />;
    case "conversation": return <Placeholder label="conversation" />;
  }
}

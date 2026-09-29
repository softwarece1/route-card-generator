import { Button } from "primereact/button";
import { useTheme } from "@/providers/ThemeProvider";

/**
 * Icon button that toggles light / dark theme.
 */
export default function ThemeToggle({ className = "", size = "small" }) {
  const { isDark, toggleTheme } = useTheme();

  return (
    <Button
      type="button"
      icon={isDark ? "pi pi-sun" : "pi pi-moon"}
      rounded
      text
      size={size}
      className={`rc-theme-toggle ${className}`.trim()}
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      tooltip={isDark ? "Light theme" : "Dark theme"}
      tooltipOptions={{ position: "bottom" }}
      onClick={toggleTheme}
    />
  );
}

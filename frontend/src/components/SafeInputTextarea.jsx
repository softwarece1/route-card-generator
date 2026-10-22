import { InputTextarea } from "primereact/inputtextarea";
import { sanitizeInput } from "@/lib/inputSafe";

/**
 * InputTextarea with multiline-safe sanitization (strips HTML / injection tokens).
 */
export default function SafeInputTextarea({
  profile = "multiline",
  value,
  onChange,
  maxLength,
  ...rest
}) {
  const handleChange = (e) => {
    const { value: next } = sanitizeInput(e.target.value, profile);
    if (!onChange) return;
    onChange({
      ...e,
      target: { ...e.target, value: next },
      value: next,
    });
  };

  return (
    <InputTextarea
      {...rest}
      value={value ?? ""}
      onChange={handleChange}
      maxLength={maxLength}
    />
  );
}

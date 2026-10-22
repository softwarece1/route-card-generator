import { InputText } from "primereact/inputtext";
import { sanitizeInput } from "@/lib/inputSafe";

/**
 * InputText that strips unsafe / unrelated characters on every change.
 * @param {'empId'|'personName'|'label'|'code'|'password'|'search'|'text'} profile
 */
export default function SafeInputText({
  profile = "text",
  value,
  onChange,
  maxLength,
  ...rest
}) {
  const handleChange = (e) => {
    const { value: next } = sanitizeInput(e.target.value, profile);
    if (!onChange) return;
    // Synthesize event-like object so existing handlers keep working
    onChange({
      ...e,
      target: { ...e.target, value: next },
      value: next,
    });
  };

  return (
    <InputText
      {...rest}
      value={value ?? ""}
      onChange={handleChange}
      maxLength={maxLength}
      autoComplete={rest.autoComplete}
    />
  );
}

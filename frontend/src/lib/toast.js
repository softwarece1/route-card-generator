import hotToast from "react-hot-toast";

function message(detail, summary) {
  const d = detail == null ? "" : String(detail);
  const s = summary == null ? "" : String(summary);
  if (d && s) return `${s}: ${d}`;
  return d || s || "";
}

export const toast = {
  success: (detail, summary) =>
    hotToast.success(message(detail, summary), { duration: 3000 }),
  error: (detail, summary) =>
    hotToast.error(message(detail, summary), { duration: 5000 }),
  warn: (detail, summary) =>
    hotToast(message(detail, summary), { icon: "⚠️", duration: 3500 }),
  info: (detail, summary) =>
    hotToast(message(detail, summary), { duration: 3000 }),
};


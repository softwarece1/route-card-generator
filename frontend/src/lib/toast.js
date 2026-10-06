import hotToast from "react-hot-toast";

function message(detail, summary) {
  const d = detail == null ? "" : String(detail);
  const s = summary == null ? "" : String(summary);
  if (d && s) return `${s}: ${d}`;
  return d || s || "";
}

const base = {
  className: "rc-hot-toast",
};

export const toast = {
  success: (detail, summary) =>
    hotToast.success(message(detail, summary), {
      ...base,
      className: "rc-hot-toast rc-hot-toast--success",
      duration: 3000,
    }),
  error: (detail, summary) =>
    hotToast.error(message(detail, summary), {
      ...base,
      className: "rc-hot-toast rc-hot-toast--error",
      duration: 5000,
    }),
  warn: (detail, summary) =>
    hotToast(message(detail, summary), {
      ...base,
      className: "rc-hot-toast rc-hot-toast--warn",
      icon: "⚠️",
      duration: 3500,
    }),
  info: (detail, summary) =>
    hotToast(message(detail, summary), {
      ...base,
      className: "rc-hot-toast rc-hot-toast--info",
      duration: 3000,
    }),
  loading: (detail, summary) =>
    hotToast.loading(message(detail, summary), {
      ...base,
      className: "rc-hot-toast rc-hot-toast--loading",
    }),
  dismiss: (id) => hotToast.dismiss(id),
};

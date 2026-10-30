/**
 * Client-side input hardening — strip / reject payloads attackers often use
 * (HTML/JS injection, control chars, path tricks) while allowing normal
 * manufacturing text and passwords.
 */

const CTRL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;
const CTRL_KEEP_NL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;
const HTML_TAG = /<\/?[a-zA-Z][^>]*>/g;
const DANGEROUS_TOKEN =
  /(?:javascript|vbscript|data)\s*:|on(?:error|load|click|mouse\w+|focus|blur|submit|toggle)\s*=|<\s*(?:script|iframe|object|embed|link|meta|svg|img)\b/gi;
const PATH_TRAVERSAL = /(?:^|[\\/])\.\.(?:[\\/]|$)/g;

/** Allowed character classes per profile (after stripping danger). */
const PROFILES = {
  /** Employee ID: digits, or literal admin */
  empId: {
    max: 64,
    allow: /[^0-9a-zA-Z]/g,
    message: "Employee ID may only contain letters and digits",
  },
  /** Person name */
  personName: {
    max: 255,
    allow: /[^a-zA-Z\s.'\-]/g,
    message: "Name may only contain letters, spaces, . ' -",
  },
  /** Department / short labels from forms */
  label: {
    max: 128,
    allow: /[^a-zA-Z0-9\s.\-_/()#+&]/g,
    message: "Only letters, numbers, and basic punctuation are allowed",
  },
  /** Work centre / machine / tool / op titles */
  code: {
    max: 200,
    allow: /[^a-zA-Z0-9\s.\-_/()#+&,:%°]/g,
    message: "Only letters, numbers, and basic punctuation are allowed",
  },
  /** Passwords: printable ASCII except < > ` and controls */
  password: {
    max: 128,
    allow: /[^\x20-\x7E]|[<>`]/g,
    message: "Password contains unsupported characters",
  },
  /** Search / filter text */
  search: {
    max: 120,
    allow: /[^a-zA-Z0-9\s.\-_/()#]/g,
    message: "Search text contains unsupported characters",
  },
  /** Multi-line instructions / notes / prompt addenda */
  multiline: {
    max: 8000,
    allow: null, // strip danger only; keep punctuation
    message: "Text contains unsupported or unsafe content",
  },
  /** Route-card discussion remarks */
  remark: {
    max: 4000,
    allow: /[^a-zA-Z0-9\s.\-_/()#+&,:%°@'!?;:\n]/g,
    message: "Only letters, numbers, and basic punctuation are allowed",
  },
  /** Generic single-line (default) */
  text: {
    max: 500,
    allow: /[^a-zA-Z0-9\s.\-_/()#+&,:%°@']/g,
    message: "Only letters, numbers, and basic punctuation are allowed",
  },
};

function stripDanger(raw, { keepNewlines = false } = {}) {
  let s = String(raw ?? "");
  s = s.replace(keepNewlines ? CTRL_KEEP_NL : CTRL, "");
  s = s.replace(HTML_TAG, "");
  s = s.replace(DANGEROUS_TOKEN, "");
  s = s.replace(PATH_TRAVERSAL, "");
  s = s.replace(/\.\./g, ""); // path traversal / probe fragments
  // Angle brackets are common in XSS probes
  s = s.replace(/[<>]/g, "");
  return s;
}

/**
 * Sanitize a string for the given profile. Always strips control/HTML/injection tokens.
 * @returns {{ value: string, changed: boolean, blocked: boolean, message: string }}
 */
export function sanitizeInput(raw, profile = "text") {
  const cfg = PROFILES[profile] || PROFILES.text;
  const keepNewlines = profile === "multiline" || profile === "remark";
  const original = String(raw ?? "");
  let value = stripDanger(original, { keepNewlines });
  if (cfg.allow) {
    value = value.replace(cfg.allow, "");
  }
  if (value.length > cfg.max) {
    value = value.slice(0, cfg.max);
  }
  const changed = value !== original;
  // "blocked" if the user tried to enter only dangerous content that vanished
  const blocked = Boolean(original.trim()) && !value.trim() && changed;
  return {
    value,
    changed,
    blocked,
    message: blocked || changed ? cfg.message : "",
  };
}

/** True if the value is acceptable for the profile (after sanitize equals input). */
export function isInputSafe(raw, profile = "text") {
  const { value, changed } = sanitizeInput(raw, profile);
  if (profile === "password") {
    return !changed && value.length >= 1;
  }
  return !changed;
}

export function sanitizeInputEvent(e, profile = "text") {
  const next = sanitizeInput(e?.target?.value, profile);
  return next.value;
}

export const INPUT_PROFILES = Object.keys(PROFILES);

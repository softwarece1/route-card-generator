/** Sentence-case OCR ALL-CAPS shop instructions for display / edit. */

const KEEP_ACRONYMS = new Set([
  "GA",
  "PCB",
  "PCBA",
  "CTQ",
  "DC",
  "AC",
  "WL",
  "PL",
  "BOM",
  "OARC",
  "ISO",
  "DIN",
  "IEC",
  "EMI",
  "ESD",
  "SMT",
  "THT",
  "LED",
  "LCD",
  "USB",
  "RF",
  "NM",
  "MM",
  "IP",
  "QC",
  "QA",
  "SOP",
]);

const ACRONYM_RE = new RegExp(
  `\\b(?:${[...KEEP_ACRONYMS].sort((a, b) => b.length - a.length).join("|")})\\b`,
  "gi"
);
const CONNECTOR_RE = /\b[JPCX]\d{1,3}\b/gi;
const PART_GROUP_RE = /\b\d{3,}(?:\s+\d{2,}){1,4}\b/g;
const LIST_PREFIX_RE = /^(\s*(?:[a-z]\)|\d{1,3}\)|\([a-z]\)|[ivx]+\))\s+)(.*)$/i;

function capFirstAlpha(s) {
  const str = String(s || "");
  for (let i = 0; i < str.length; i += 1) {
    if (/[A-Za-z]/.test(str[i])) {
      return str.slice(0, i) + str[i].toUpperCase() + str.slice(i + 1);
    }
  }
  return str;
}

function capitalizeSentences(chunk) {
  const parts = String(chunk || "").split(/([.!?]\s+)/);
  let capNext = true;
  return parts
    .map((part) => {
      if (/^[.!?]\s+$/.test(part)) {
        capNext = true;
        return part;
      }
      if (capNext && part) {
        capNext = false;
        return capFirstAlpha(part);
      }
      return part;
    })
    .join("");
}

/**
 * Normalize mostly-uppercase instruction / description text to sentence case.
 * Leaves already-mixed text alone. Preserves acronyms, connectors, part-number groups.
 */
export function normalizeInstructionCase(text) {
  const raw = String(text || "");
  if (!raw) return "";
  const letters = [...raw].filter((c) => /[A-Za-z]/.test(c));
  if (!letters.length) return raw;
  const upperRatio = letters.filter((c) => c === c.toUpperCase()).length / letters.length;
  if (upperRatio < 0.65) return raw;

  const tokens = [];
  const protect = (match) => {
    tokens.push(match);
    return `\u0000${tokens.length - 1}\u0000`;
  };

  let out = raw;
  out = out.replace(PART_GROUP_RE, protect);
  out = out.replace(CONNECTOR_RE, protect);
  out = out.replace(ACRONYM_RE, protect);
  out = out.toLowerCase();

  out = out
    .split("\n")
    .map((line) => {
      const m = line.match(LIST_PREFIX_RE);
      if (m) return `${m[1].toLowerCase()}${capitalizeSentences(m[2])}`;
      return capitalizeSentences(line);
    })
    .join("\n");

  out = out.replace(
    /\bitem\s*(?:no\.?|nos\.?|number|#)?\s*-?\s*(\d{1,3})\b/gi,
    (_full, num) => `Item No. ${num}`
  );

  tokens.forEach((tok, i) => {
    let restored = tok;
    if (KEEP_ACRONYMS.has(String(tok || "").toUpperCase())) {
      restored = String(tok).toUpperCase();
    } else if (/^[JPCX]\d{1,3}$/i.test(tok || "")) {
      restored = tok[0].toUpperCase() + tok.slice(1);
    }
    out = out.split(`\u0000${i}\u0000`).join(restored);
  });
  return out;
}

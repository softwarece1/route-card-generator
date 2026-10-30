/**
 * Enterprise Password Policy & Utility (VAPT Compliant)
 */

export const PASSWORD_RULES = [
  { id: "length", label: "Contain at least 12 characters", test: (p) => p && p.length >= 12 },
  { id: "maxLength", label: "Not exceed 64 characters", test: (p) => p && p.length <= 64 },
  { id: "uppercase", label: "Contain at least one uppercase letter (A-Z)", test: (p) => /[A-Z]/.test(p || "") },
  { id: "lowercase", label: "Contain at least one lowercase letter (a-z)", test: (p) => /[a-z]/.test(p || "") },
  { id: "number", label: "Contain at least one number (0-9)", test: (p) => /\d/.test(p || "") },
  { id: "special", label: "Contain at least one special character (!@#$%^&*...)", test: (p) => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?]/.test(p || "") },
  { id: "noSpace", label: "Not contain spaces or whitespace", test: (p) => !/\s/.test(p || "") },
];

export const COMMON_PASSWORDS = new Set([
  "password", "password123", "admin123456", "123456789012",
  "welcome12345", "qwerty123456", "routecard123", "administrator",
]);

export function getPasswordErrors(pwd) {
  if (!pwd) {
    return [
      "Contain at least 12 characters",
      "Contain at least one uppercase letter (A-Z)",
      "Contain at least one lowercase letter (a-z)",
      "Contain at least one number (0-9)",
      "Contain at least one special character",
      "Not contain spaces or whitespace",
    ];
  }
  const failed = [];
  for (const rule of PASSWORD_RULES) {
    if (!rule.test(pwd)) {
      failed.push(rule.label);
    }
  }
  if (COMMON_PASSWORDS.has(pwd.toLowerCase())) {
    failed.push("Not be a commonly used or compromised password");
  }
  return failed;
}

/**
 * Generate a cryptographically random, compliant temporary password (14 characters)
 * containing uppercase, lowercase, numbers, and special characters.
 */
export function generateCompliantPassword(length = 14) {
  const uppers = "ABCDEFGHJKLMNPQRSTUVWXYZ"; // exclude easily confused I, O
  const lowers = "abcdefghijkmnpqrstuvwxyz"; // exclude easily confused l, o
  const digits = "23456789";                  // exclude easily confused 0, 1
  const specials = "!@#$%^&*_-+=";
  const allChars = uppers + lowers + digits + specials;

  const getRandom = (str) => {
    const array = new Uint32Array(1);
    window.crypto.getRandomValues(array);
    return str[array[0] % str.length];
  };

  // Guarantee at least 2 of each class
  const pwdChars = [
    getRandom(uppers), getRandom(uppers),
    getRandom(lowers), getRandom(lowers),
    getRandom(digits), getRandom(digits),
    getRandom(specials), getRandom(specials),
  ];

  while (pwdChars.length < Math.max(12, length)) {
    pwdChars.push(getRandom(allChars));
  }

  // Cryptographic in-place Fisher-Yates shuffle
  for (let i = pwdChars.length - 1; i > 0; i--) {
    const array = new Uint32Array(1);
    window.crypto.getRandomValues(array);
    const j = array[0] % (i + 1);
    [pwdChars[i], pwdChars[j]] = [pwdChars[j], pwdChars[i]];
  }

  const generated = pwdChars.join("");
  // Sanity check against rules
  if (getPasswordErrors(generated).length > 0) {
    return generateCompliantPassword(length);
  }
  return generated;
}

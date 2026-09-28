import logoSrc from "@/assets/route-card-logo.svg";

/** Subtle AI Route Card mark for auth screens (~40px). */
export default function AuthLogo({ size = 40, className = "" }) {
  return (
    <img
      src={logoSrc}
      alt=""
      width={size}
      height={size}
      className={`rc-auth-logo ${className}`.trim()}
      draggable={false}
    />
  );
}

import React from "react";

/**
 * Unified page header — same layout as PMF standalone (`nd-header`).
 *
 * @param {string} title
 * @param {string} [subtitle]
 * @param {string} [icon] PrimeIcons class, e.g. "pi pi-home"
 * @param {React.ReactNode} [actions] Right-side controls
 * @param {string} [className]
 * @param {string} [as] Root element tag, default "div"
 */
export default function PageHeader({
  title,
  subtitle,
  icon = "pi pi-th-large",
  actions,
  className = "",
  as: Root = "div",
}) {
  return (
    <Root className={`nd-header${className ? ` ${className}` : ""}`}>
      <div className="nd-header__left">
        <div className="nd-header__title-wrap">
          <div className="nd-header__icon" aria-hidden>
            <i className={icon} />
          </div>
          <div>
            <h1 className="nd-header__title">{title}</h1>
            {subtitle ? <p className="nd-header__subtitle">{subtitle}</p> : null}
          </div>
        </div>
      </div>
      {actions ? <div className="nd-header__actions">{actions}</div> : null}
    </Root>
  );
}

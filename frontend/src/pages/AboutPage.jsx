import { Link } from "react-router-dom";
import { Button } from "primereact/button";
import { isAuthenticated, getUser } from "@/lib/auth";
import ThemeToggle from "@/components/ThemeToggle";
import logoSvg from "@/assets/route-card-logo.svg";
import heroImg from "@/assets/hero.png";
import workflowImg from "@/assets/about-workflow.png";
import "./about.scss";

const GUIDE_STEPS = [
  {
    n: "1",
    icon: "pi pi-sign-in",
    title: "Sign in",
    text: "Create an account or log in with your Employee ID. Engineers, department heads, and admins each see the tools for their role.",
  },
  {
    n: "2",
    icon: "pi pi-upload",
    title: "Open Generator and upload documents",
    text: "Go to Generator. Upload the Drawing (GA) — PDF or TIFF — and the Parts List (PDF or Excel). Add a Wire List if the assembly needs it.",
  },
  {
    n: "3",
    icon: "pi pi-bolt",
    title: "Generate the OARC",
    text: "Click Generate OARC. The app reads the drawing and parts list, recovers operation instructions from the document, and builds a draft route sequence.",
  },
  {
    n: "4",
    icon: "pi pi-pencil",
    title: "Review and edit the route",
    text: "Check operations, work centres, tools, items, and instruction text. Add or adjust steps. Apply an operation template from your department when it fits.",
  },
  {
    n: "5",
    icon: "pi pi-save",
    title: "Save and print",
    text: "Save the draft route card, open the OARC preview, and print or export for the shop floor. Find past work anytime under Extractions.",
  },
];

const CAPABILITIES = [
  {
    icon: "pi pi-file",
    title: "Drawing & parts upload",
    text: "Accept GA drawings and Parts Lists (Wire List optional) so the route starts from the real document pack.",
  },
  {
    icon: "pi pi-book",
    title: "Operation instructions",
    text: "Pull assembly and operation instructions from the drawing into clear, editable route steps.",
  },
  {
    icon: "pi pi-sitemap",
    title: "Route card draft",
    text: "Suggest a sequenced OARC with work centres, tooling cues, items, and long-text instructions.",
  },
  {
    icon: "pi pi-clone",
    title: "Templates & team roles",
    text: "Reuse department operation packs. Dept heads manage engineers; admins oversee users across departments.",
  },
];

const BG_ICONS_LEFT = [
  { icon: "pi pi-cog", top: "8%", size: "3.2rem", opacity: 0.14 },
  { icon: "pi pi-wrench", top: "28%", size: "2.4rem", opacity: 0.11 },
  { icon: "pi pi-sitemap", top: "48%", size: "2.8rem", opacity: 0.12 },
  { icon: "pi pi-compass", top: "68%", size: "2.2rem", opacity: 0.1 },
  { icon: "pi pi-sliders-h", top: "86%", size: "2.6rem", opacity: 0.11 },
];

const BG_ICONS_RIGHT = [
  { icon: "pi pi-cog", top: "12%", size: "2.8rem", opacity: 0.12 },
  { icon: "pi pi-box", top: "32%", size: "2.3rem", opacity: 0.1 },
  { icon: "pi pi-file", top: "52%", size: "2.6rem", opacity: 0.12 },
  { icon: "pi pi-print", top: "72%", size: "2.4rem", opacity: 0.1 },
  { icon: "pi pi-check-circle", top: "90%", size: "2.2rem", opacity: 0.11 },
];

export default function AboutPage() {
  const loggedIn = isAuthenticated();
  const user = getUser();

  return (
    <div className="rc-landing">
      <div className="rc-landing__bg" aria-hidden>
        <div className="rc-landing__bg-side rc-landing__bg-side--left">
          {BG_ICONS_LEFT.map((item, i) => (
            <i
              key={`L${i}`}
              className={`rc-landing__bg-icon ${item.icon}`}
              style={{
                top: item.top,
                fontSize: item.size,
                "--icon-opacity": item.opacity,
              }}
            />
          ))}
        </div>
        <div className="rc-landing__bg-side rc-landing__bg-side--right">
          {BG_ICONS_RIGHT.map((item, i) => (
            <i
              key={`R${i}`}
              className={`rc-landing__bg-icon ${item.icon}`}
              style={{
                top: item.top,
                fontSize: item.size,
                "--icon-opacity": item.opacity,
              }}
            />
          ))}
        </div>
      </div>

      <header className="rc-landing__nav">
        <div className="rc-landing__nav-inner">
          <Link to="/" className="rc-landing__brand">
            <img src={logoSvg} alt="" className="rc-landing__brand-logo" />
            <span>
              <strong>OARC</strong>
              <em>Route Card</em>
            </span>
          </Link>
          <div className="rc-landing__nav-actions">
            <ThemeToggle />
            {loggedIn ? (
              <>
                <span className="rc-landing__nav-user">
                  {user?.display_name || user?.name || user?.empId || "Signed in"}
                </span>
                <Link to="/generator">
                  <Button type="button" label="Open Generator" icon="pi pi-bolt" size="small" />
                </Link>
              </>
            ) : (
              <>
                <Link to="/login">
                  <Button type="button" label="Login" outlined size="small" />
                </Link>
                <Link to="/signup">
                  <Button type="button" label="Sign up" icon="pi pi-user-plus" size="small" />
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main className="rc-landing__main">
        <section className="rc-landing__hero">
          <div className="rc-landing__hero-copy">
            <p className="rc-landing__eyebrow">Automated Operation &amp; Route Card</p>
            <h1>Automated OARC from your drawings</h1>
            <p className="rc-landing__lead">
              Upload your GA drawing and Parts List, turn operation instructions into a draft route,
              then review, edit, and print a shop-ready OARC.
            </p>
            <div className="rc-landing__cta">
              {loggedIn ? (
                <Link to="/generator">
                  <Button type="button" label="Open Generator" icon="pi pi-bolt" />
                </Link>
              ) : (
                <>
                  <Link to="/signup">
                    <Button type="button" label="Get started" icon="pi pi-arrow-right" iconPos="right" />
                  </Link>
                  <Link to="/login">
                    <Button type="button" label="Sign in" outlined />
                  </Link>
                </>
              )}
            </div>
          </div>
          <div className="rc-landing__hero-visual">
            <img src={heroImg} alt="Route card product visual" />
          </div>
        </section>

        <section className="rc-landing__panel">
          <div className="rc-landing__panel-copy">
            <h2>What you get</h2>
            <p>
              One place to upload the drawing pack, generate an operation sequence from the
              document&apos;s operation instructions, refine it with your team&apos;s templates, and
              issue the route card for production.
            </p>
          </div>
          <img
            className="rc-landing__panel-img"
            src={workflowImg}
            alt="Workflow from drawing and parts list to route card"
          />
        </section>

        <section className="rc-landing__section" aria-label="User guide">
          <div className="rc-landing__section-head">
            <h2>User guide — what to do</h2>
            <p>Follow these steps the first time you use the Generator.</p>
          </div>
          <ol className="rc-landing__guide">
            {GUIDE_STEPS.map((s) => (
              <li key={s.n} className="rc-landing__guide-item">
                <div className="rc-landing__guide-mark" aria-hidden>
                  <span className="rc-landing__guide-n">{s.n}</span>
                  <span className="rc-landing__guide-icon">
                    <i className={s.icon} />
                  </span>
                </div>
                <div className="rc-landing__guide-copy">
                  <strong>{s.title}</strong>
                  <p>{s.text}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="rc-landing__section" aria-label="Capabilities">
          <div className="rc-landing__section-head">
            <h2>At a glance</h2>
            <p>The main pieces of the OARC workflow.</p>
          </div>
          <div className="rc-landing__cap-grid">
            {CAPABILITIES.map((c) => (
              <article key={c.title} className="rc-landing__cap">
                <i className={c.icon} aria-hidden />
                <h3>{c.title}</h3>
                <p>{c.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="rc-landing__cta-band">
          <div>
            <h2>Ready to build a route card?</h2>
            <p>Sign in and open Generator to upload your first drawing pack.</p>
          </div>
          {loggedIn ? (
            <Link to="/generator">
              <Button type="button" label="Open Generator" icon="pi pi-bolt" />
            </Link>
          ) : (
            <div className="rc-landing__cta">
              <Link to="/signup">
                <Button type="button" label="Sign up" icon="pi pi-user-plus" />
              </Link>
              <Link to="/login">
                <Button type="button" label="Login" outlined />
              </Link>
            </div>
          )}
        </section>
      </main>

      <footer className="rc-landing__foot">
        <div className="rc-landing__foot-inner">
          <p>Automated OARC Generator</p>
          {!loggedIn ? (
            <div className="rc-landing__foot-actions">
              <Link to="/login">Login</Link>
              <span aria-hidden>·</span>
              <Link to="/signup">Sign up</Link>
            </div>
          ) : null}
        </div>
      </footer>
    </div>
  );
}

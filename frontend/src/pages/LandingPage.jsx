import { useNavigate } from "react-router-dom";
import { homeFor, useAuth } from "../auth.jsx";
import "./LandingPage.css";

// Served from frontend/public/ so the JS bundle stays small.
const TEAM_PHOTO = "/team-photo.jpeg";

const TEAM_MEMBERS = [
  { initials: "RD", name: "Rajdeep Das", role: "Software Engineering", href: "https://www.linkedin.com/in/rajdeep-das-007x925/" },
  { initials: "JS", name: "Jade Sharpe", role: "Commerce" },
  { initials: "MI", name: "Maryam Ibrahim", role: "Business & Psychology" },
  { initials: "AI", name: "Adanna Izugbokwe", role: "Urban & Architectural Studies" },
  { initials: "ME", name: "Mahmood Elahi", role: "Engineering" },
  { initials: "AS", name: "Adrina Sadeghian", role: "Software Engineering" },
];

const NEWS_URL =
  "https://experienceventures.ca/how-six-students-tackled-calgarys-housing-challenge-in-three-days/";

const STEPS = [
  { title: "Submit your intake", body: "Tell us about your property, whether a suite exists, and what you know about its current state. Takes about 10 minutes." },
  { title: "We assess eligibility", body: "We check your zoning district, review your documents, and flag any compliance gaps before anything starts." },
  { title: "Site visit", body: "One of our team visits your property to assess what needs to be done and produce a cost estimate." },
  { title: "We handle everything", body: "Permits, contractors, city inspections, financing connections. You track progress in your dashboard." },
  { title: "Your suite is legal", body: "Inspected, registered, and ready to rent. We handle the certificate; you collect rent." },
];

function HouseIcon({ label = "Ready2Rent house icon" }) {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label={label}>
      <g id="home-symbol">
        <path
          fill="#176B50"
          fillRule="evenodd"
          d="M16 56 Q16 52 20 49 L58 19 Q64 14 70 19 L108 49 Q112 52 112 56 V106 Q112 114 104 114 H24 Q16 114 16 106 Z M51 65 Q48 65 48 68 V114 H80 V68 Q80 65 77 65 Z"
        />
        <path fill="#71C6A3" d="M52 69 L73 76 Q76 77 76 80 V111 Q76 114 73 113 L52 106 Z" />
        <circle cx="69" cy="94" r="2" fill="#176B50" />
      </g>
    </svg>
  );
}

function Logo({ size = "md" }) {
  return (
    <div className={`lp-logo lp-logo--${size}`}>
      <HouseIcon />
      <span className="lp-logo-text">
        Ready<em>2</em>Rent
      </span>
    </div>
  );
}

function scrollTo(e, id) {
  e.preventDefault();
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth" });
}

function Navbar({ onApply }) {
  return (
    <nav className="lp-nav">
      <div className="lp-container lp-nav-inner">
        <Logo />
        <div className="lp-nav-links">
          <a href="#about" onClick={(e) => scrollTo(e, "about")}>About</a>
          <a href="#team" onClick={(e) => scrollTo(e, "team")}>Team</a>
          <a href="#howitworks" onClick={(e) => scrollTo(e, "howitworks")}>How it works</a>
          <button type="button" className="lp-btn lp-btn--primary" onClick={onApply}>
            Start application
          </button>
        </div>
      </div>
    </nav>
  );
}

function Hero({ onApply }) {
  return (
    <section className="lp-hero">
      <div className="lp-container">
        <div className="lp-hero-inner">
          <div className="lp-hero-badge">
            <span>🏆 Experience Ventures Hackathon winners · University of Calgary 2026</span>
          </div>
          <h1>
            Your basement,<br />
            <span>Someone's next home.</span>
          </h1>
          <p>
            We navigate the permits, contractors, and city paperwork so Calgary homeowners
            can turn unpermitted suites into legal, rentable income without the uncertainty.
          </p>
          <div className="lp-hero-actions">
            <button type="button" className="lp-btn lp-btn--primary lp-btn--lg" onClick={onApply}>
              Start your application
            </button>
            <a href="#howitworks" className="lp-btn lp-btn--ghost" onClick={(e) => scrollTo(e, "howitworks")}>
              How it works
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function AboutSection() {
  return (
    <section id="about" className="lp-section">
      <div className="lp-container">
        <div className="lp-about-intro">
          <p className="lp-eyebrow">Our story</p>
          <h2>Born at a hackathon, built into a real product</h2>
          <p className="lp-lead">
            Ready2Rent began with six University of Calgary students and a shared goal: help more
            Calgarians find a safe place to call home. Over three days at the Experience Ventures
            Hackathon, we developed an idea inspired by our teammate Rajdeep Das’s experience living
            in an unpermitted basement suite, helping homeowners navigate the uncertainty of bringing
            their suites up to code. That idea won the top prize. Today, we’re building it into a
            practical platform that brings permits, documents, and progress together, making the path
            from basement suite to someone’s next home easier to follow.
          </p>
        </div>

        <div className="lp-photo-card">
          <img
            src={TEAM_PHOTO}
            alt="Ready2Rent team holding the winner cheque at the Experience Ventures Hackathon"
          />
          <p className="lp-photo-caption">
            Team Ready2Rent at the Experience Ventures Affordable Housing Hackathon,
            University of Calgary · February 2026
          </p>
        </div>

        <div className="lp-news">
          <div className="lp-news-icon">
            <span>📰</span>
          </div>
          <div>
            <p className="lp-news-title">
              How six students tackled Calgary's housing challenge in three days
            </p>
            <p className="lp-news-meta">Experience Ventures · February 19, 2026</p>
            <a href={NEWS_URL} target="_blank" rel="noopener noreferrer">
              ↗ experienceventures.ca
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}

function TeamSection() {
  return (
    <section id="team" className="lp-section">
      <div className="lp-container">
        <p className="lp-eyebrow">The team</p>
        <h2>Six disciplines, one mission</h2>
        <div className="lp-team-grid">
          {TEAM_MEMBERS.map((m) => {
            const body = (
              <>
                <div className="lp-avatar">{m.initials}</div>
                <div>
                  <p className="lp-member-name">{m.name}</p>
                  <p className="lp-member-role">{m.role}</p>
                </div>
              </>
            );
            // Members with a profile link render the whole card as a link (opens in a new tab).
            return m.href ? (
              <a
                key={m.initials}
                className="lp-member lp-member--link"
                href={m.href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${m.name} on LinkedIn`}
              >
                {body}
              </a>
            ) : (
              <div key={m.initials} className="lp-member">{body}</div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function HowItWorksSection() {
  return (
    <section id="howitworks" className="lp-section">
      <div className="lp-container lp-how-grid">
        <div className="lp-how-head">
          <p className="lp-eyebrow">How it works</p>
          <h2>From application to legal in five steps</h2>
        </div>
        <div className="lp-steps">
          {STEPS.map((s, i) => (
            <div key={s.title} className="lp-step">
              <div className="lp-step-num">{i + 1}</div>
              <div className="lp-measure">
                <p className="lp-step-title">{s.title}</p>
                <p className="lp-step-body">{s.body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="lp-footer">
      <div className="lp-container lp-footer-inner">
        <Logo size="sm" />
        <p>© 2026 Ready2Rent · University of Calgary</p>
        <p>Designed and built by Rajdeep Das</p>
      </div>
    </footer>
  );
}

export default function LandingPage() {
  const navigate = useNavigate();
  const { status, user } = useAuth();

  // The homeowner signup built in Milestone 2 lives at /register (a /signup alias also
  // redirects there). Someone already signed in goes straight to their dashboard.
  // Client-side navigation keeps the in-memory session instead of a full page reload.
  const handleApply = () => {
    navigate(status === "authed" ? homeFor(user) : "/register");
  };

  return (
    <div className="lp">
      <Navbar onApply={handleApply} />
      <Hero onApply={handleApply} />
      <AboutSection />
      <TeamSection />
      <HowItWorksSection />
      <Footer />
    </div>
  );
}

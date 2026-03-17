import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: {
    absolute: "Heidi Tender",
  },
  description: "Traceable tender intelligence for lighting engineering and bid teams.",
};

const heroMetrics = [
  {
    value: "200",
    label: "pages per submission",
    note: "Dense tender dossiers, specs, annexes, and product constraints.",
  },
  {
    value: "3h",
    label: "manual search per project",
    note: "Spent crossing PDFs, spreadsheets, catalogues, and supplier portals.",
  },
  {
    value: "13x",
    label: "day-one return",
    note: "On the first 100 submissions, the client cost is only a fraction of the saved engineering time.",
  },
];

const fragmentSources = ["Word files", "Excel sheets", "PDF catalogues", "Supplier portals", "Human memory", "Endless cross-checking"];

const problemStats = [
  {
    value: "200-page",
    label: "typical lighting submission",
    detail: "Specifications, annexes, norms, product schedules, and scattered supplier references.",
  },
  {
    value: "50",
    label: "projects per year",
    detail: "A realistic annual bid load for a firm running repeated manual search and checking cycles.",
  },
  {
    value: "150h",
    label: "expert time lost",
    detail: "Three hours per project becomes a recurring hidden cost at every tendering team.",
  },
];

const workflowSteps = [
  {
    number: "01",
    title: "Read the submission",
    body: "The agent parses the tender dossier, annexes, and schedules into a structured starting point instead of leaving critical details trapped in long documents.",
  },
  {
    number: "02",
    title: "Extract structured requirements",
    body: "Room types, lux levels, IP ratings, norms, controls, and other constraints are pulled into a machine-readable brief.",
  },
  {
    number: "03",
    title: "Apply governed rules",
    body: "Explicit matching rules stay versioned, reviewable, and explainable so the workflow remains defensible for bid teams.",
  },
  {
    number: "04",
    title: "Match real catalog products",
    body: "The system filters against the client's private rational database and ranks only products that actually exist in supplier data.",
  },
];

const proofColumns = [
  {
    label: "Requirement",
    title: "Structured tender brief",
    rows: ["Room type: classroom", "Target illuminance: 500 lux", "IP rating: IP54", "Norm: EN 12464-1"],
  },
  {
    label: "Rule",
    title: "Governed matching logic",
    rows: ["Hard: direct_ugr <= 19", "Hard: ingress protection", "Soft: efficacy and output", "Soft: control compatibility"],
  },
  {
    label: "Catalog",
    title: "Private database reality",
    rows: ["Normalized supplier attributes", "Only existing SKUs are considered", "Client rational database stays private", "Every filter remains inspectable"],
  },
  {
    label: "Ranked result",
    title: "Defensible shortlist",
    rows: ["Passes hard constraints", "Soft score: 0.91", "DALI match retained", "Why ranked: glare + IP + control fit"],
  },
];

const clientEconomics = [
  { value: "CHF 34'000", label: "engineer time saved", detail: "Across 100 submissions." },
  { value: "CHF 2'500", label: "client cost", detail: "Only 7% of the value delivered." },
  { value: "13x", label: "return on day one", detail: "Immediate ROI once submissions start flowing." },
];

const marketEconomics = [
  { value: "1'500", label: "firms in Switzerland", detail: "Submitting lighting tenders annually." },
  { value: "150'000", label: "submissions / year", detail: "Approximate market volume." },
  { value: "15'000", label: "submissions at 10%", detail: "With roughly 150 clients in year one." },
  { value: "CHF 1'575'000", label: "year-one total", detail: "Setup revenue plus usage revenue combined." },
];

const revenueStreams = [
  "CHF 10'000 one-time database setup per client.",
  "CHF 25 per submission processed.",
];

export default function LandingPage() {
  return (
    <div className="landing-page">
      <section className="landing-band landing-hero-band landing-reveal">
        <div className="page-wrap landing-hero-grid">
          <div className="landing-copy">
            <span className="landing-eyebrow">Traceable tender intelligence for lighting teams</span>
            <h1 className="landing-title">
              Turn <span className="landing-title-accent">200-page submissions</span> into governed, defensible lighting matches.
            </h1>
            <p className="landing-lead">
              HEIDITENDER reads tender dossiers, extracts structured requirements, applies governed rules, filters against
              real supplier catalog data, and ranks only products that actually exist.
            </p>
            <div className="landing-cta-row">
              <Link href="/console" className="btn btn-primary landing-cta-primary">
                Open Console
              </Link>
              <a href="#workflow" className="btn btn-ghost landing-cta-secondary">
                See Workflow
              </a>
            </div>
            <p className="landing-note">
              Not a generic AI chatbot. A governed workflow for bid teams that need both speed and traceable justification.
            </p>
            <div className="landing-metric-ribbon">
              {heroMetrics.map((metric) => (
                <article key={metric.label} className="landing-metric-card">
                  <p className="landing-metric-label">{metric.label}</p>
                  <p className="landing-metric-value">{metric.value}</p>
                  <p className="landing-metric-note">{metric.note}</p>
                </article>
              ))}
            </div>
          </div>

          <div className="landing-visual-shell" aria-hidden="true">
            <div className="landing-visual-grid" />
            <div className="landing-visual-beam landing-visual-beam-cool" />
            <div className="landing-visual-beam landing-visual-beam-warm" />
            <div className="landing-visual-orbit landing-visual-orbit-a" />
            <div className="landing-visual-orbit landing-visual-orbit-b" />
            <div className="landing-visual-rail" />
            <span className="landing-visual-node landing-visual-node-a" />
            <span className="landing-visual-node landing-visual-node-b" />
            <span className="landing-visual-node landing-visual-node-c" />
            <div className="landing-visual-stage">
              <article className="landing-visual-card landing-visual-card-doc">
                <span className="landing-visual-card-label">Submission</span>
                <h2 className="landing-visual-card-title">Tender dossier</h2>
                <p className="landing-visual-card-copy">200 pages / PDF schedules / annexes / supplier references</p>
              </article>
              <article className="landing-visual-card landing-visual-card-req">
                <span className="landing-visual-card-label">Extraction</span>
                <h2 className="landing-visual-card-title">Structured requirements</h2>
                <div className="landing-chip-strip">
                  <span className="landing-chip">500 lux</span>
                  <span className="landing-chip">IP54</span>
                  <span className="landing-chip">UGR &lt; 19</span>
                </div>
              </article>
              <article className="landing-visual-card landing-visual-card-rule">
                <span className="landing-visual-card-label">Governance</span>
                <h2 className="landing-visual-card-title">Versioned rules</h2>
                <p className="landing-visual-card-copy">Explicit field rules define what is hard, what is soft, and why.</p>
              </article>
              <article className="landing-visual-card landing-visual-card-db">
                <span className="landing-visual-card-label">Catalog reality</span>
                <h2 className="landing-visual-card-title">Private rational database</h2>
                <p className="landing-visual-card-copy">Only real supplier products are kept in the shortlist.</p>
              </article>
              <article className="landing-visual-card landing-visual-card-rank">
                <span className="landing-visual-card-label">Decision</span>
                <h2 className="landing-visual-card-title">Ranked shortlist</h2>
                <p className="landing-visual-card-copy">Every recommendation arrives with a traceable justification.</p>
              </article>
              <p className="landing-visual-caption">
                A traceable path from raw submission to ranked real-world product matches.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section id="problem" className="landing-section landing-anchor landing-reveal">
        <div className="page-wrap landing-section-shell">
          <div className="landing-section-grid">
            <div>
              <p className="landing-kicker">Act 1 - The Problem / Act 2 - The Status Quo is Broken</p>
              <h2 className="landing-section-title">
                Lighting engineers still stitch together bid decisions across documents, catalogues, portals, and memory.
              </h2>
              <p className="landing-section-copy">
                A lighting engineer can spend three hours in front of a 200-page submission manually searching for matching
                luminaires. Repeat that across 50 projects a year and the hidden cost becomes 150 hours of expert time lost
                to manual search, endless cross-checking, and decisions that are hard to defend later.
              </p>
              <div className="landing-fragment-row">
                {fragmentSources.map((source) => (
                  <span key={source} className="landing-fragment-chip">
                    {source}
                  </span>
                ))}
              </div>
            </div>

            <div className="landing-stat-grid">
              {problemStats.map((stat) => (
                <article key={stat.label} className="landing-stat-card">
                  <p className="landing-stat-number">{stat.value}</p>
                  <p className="landing-stat-label">{stat.label}</p>
                  <p className="landing-stat-detail">{stat.detail}</p>
                </article>
              ))}
              <article className="landing-stat-card landing-stat-card-wide">
                <p className="landing-stat-label">What breaks today</p>
                <p className="landing-quote">
                  Product data is fragmented, formats are inconsistent, and critical requirements often live in people's
                  heads instead of a governed matching workflow.
                </p>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section id="workflow" className="landing-section landing-anchor landing-reveal">
        <div className="page-wrap landing-section-shell">
          <div className="landing-section-head">
            <div>
              <p className="landing-kicker">Act 3 - The Innovation / Act 4 - The Technical Solution</p>
              <h2 className="landing-section-title landing-section-title-wide">
                Not a generic AI chatbot. A governed matching workflow for real lighting tenders.
              </h2>
            </div>
            <p className="landing-section-copy landing-section-copy-wide">
              The agent reads the submission, extracts requirements such as room types, lux levels, IP ratings, and norms,
              applies governed rules, and ranks products against the client's private rational database. The result is
              faster, more explainable, and more defensible bid selection.
            </p>
          </div>

          <div className="landing-workflow-grid">
            {workflowSteps.map((step) => (
              <article key={step.number} className="landing-workflow-card">
                <span className="landing-workflow-number">{step.number}</span>
                <h3 className="landing-workflow-title">{step.title}</h3>
                <p className="landing-workflow-copy">{step.body}</p>
              </article>
            ))}
          </div>

          <div className="landing-method-callout">
            <span className="landing-method-callout-label">Why this matters</span>
            <p className="landing-method-callout-copy">
              Every shortlisted product stays attached to the extracted requirement, the applied rule, the catalog evidence,
              and the final ranking logic.
            </p>
          </div>
        </div>
      </section>

      <section className="landing-band landing-proof-band landing-reveal">
        <div className="page-wrap landing-section-shell">
          <div className="landing-section-head">
            <div>
              <p className="landing-kicker">Evidence Chain</p>
              <h2 className="landing-section-title landing-section-title-wide">
                Every recommendation arrives with a traceable justification.
              </h2>
            </div>
            <p className="landing-section-copy landing-section-copy-wide">
              Instead of a black-box answer, HEIDITENDER preserves the chain between what the tender asked for, which rule
              was applied, what the private catalog data actually contains, and why a product was ranked higher or lower.
            </p>
          </div>

          <div className="landing-proof-grid">
            {proofColumns.map((column) => (
              <article key={column.label} className="landing-proof-card">
                <span className="landing-proof-label">{column.label}</span>
                <h3 className="landing-proof-title">{column.title}</h3>
                <ul className="landing-proof-list">
                  {column.rows.map((row) => (
                    <li key={row} className="landing-proof-item">
                      {row}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>

          <p className="landing-proof-caption">
            Bid teams can explain why a product was kept, filtered out, or ranked lower without relying on memory or manual
            post-hoc reconstruction.
          </p>
        </div>
      </section>

      <section id="economics" className="landing-section landing-anchor landing-reveal">
        <div className="page-wrap landing-section-shell">
          <div className="landing-section-head">
            <div>
              <p className="landing-kicker">Act 5 - The Business Model</p>
              <h2 className="landing-section-title landing-section-title-wide">
                Immediate client ROI, with market economics that scale.
              </h2>
            </div>
            <p className="landing-section-copy landing-section-copy-wide">
              The client case is immediate: less expert time burned on manual product search and a better audit trail for bid
              decisions. At the same time, the market and revenue model are large enough to justify building a dedicated
              operating system for lighting tenders.
            </p>
          </div>

          <div className="landing-economics-grid">
            <article className="landing-economics-panel">
              <p className="landing-panel-kicker">Client value</p>
              <div className="landing-economics-card-grid">
                {clientEconomics.map((item) => (
                  <article key={item.label} className="landing-economics-card">
                    <p className="landing-economics-value">{item.value}</p>
                    <p className="landing-economics-label">{item.label}</p>
                    <p className="landing-economics-detail">{item.detail}</p>
                  </article>
                ))}
              </div>
            </article>

            <article className="landing-economics-panel">
              <p className="landing-panel-kicker">Market and revenue</p>
              <div className="landing-economics-card-grid landing-economics-card-grid-market">
                {marketEconomics.map((item) => (
                  <article key={item.label} className="landing-economics-card">
                    <p className="landing-economics-value">{item.value}</p>
                    <p className="landing-economics-label">{item.label}</p>
                    <p className="landing-economics-detail">{item.detail}</p>
                  </article>
                ))}
              </div>
              <div className="landing-revenue-strip">
                {revenueStreams.map((item) => (
                  <p key={item} className="landing-revenue-line">
                    {item}
                  </p>
                ))}
              </div>
            </article>
          </div>
        </div>
      </section>

      <section className="landing-band landing-cta-band landing-reveal">
        <div className="page-wrap landing-closing">
          <div>
            <p className="landing-kicker">From search to decision</p>
            <h2 className="landing-section-title landing-section-title-wide">
              Move from fragmented tender search to faster, more defensible bid decisions.
            </h2>
            <p className="landing-section-copy landing-section-copy-wide">
              HEIDITENDER is designed for lighting teams that need speed, structure, and a justification trail they can
              stand behind when the bid decision matters.
            </p>
          </div>

          <div className="landing-closing-actions">
            <Link href="/console" className="btn btn-primary landing-cta-primary">
              Open Console
            </Link>
            <a href="#workflow" className="btn btn-ghost landing-cta-secondary">
              See Workflow
            </a>
          </div>
        </div>
      </section>
    </div>
  );
}

import Link from "next/link";
import { Icon } from "@/components/Icon";
import { Logo } from "@/components/Logo";
import { SignInButton } from "@/components/SignInButton";
import { ThemeToggle } from "@/components/ThemeToggle";
import { REPO_URL, SAMPLE_QUESTIONS } from "@/lib/samples";

// From backend/evals/results/answers-gemini.md (Gemini embeddings, gpt-oss-120b, all nine documents).
const EVIDENCE = [
  { big: "94%", text: "of answers cite a source and stay grounded (100 of 106)" },
  { big: "8 of 8", text: "out-of-scope questions refused instead of invented" },
  { big: "18 of 18", text: "near-miss questions answered with “the document doesn't say”" },
  { big: "106", text: "hand-checked questions across 9 public documents" },
];

const STEPS = [
  { icon: "up", title: "Add documents", text: "Use the sample contracts or upload a PDF. Text is split by page, so a citation always means exactly one page." },
  { icon: "search", title: "Ask in plain words", text: "Hybrid search finds the passages, and follow-up questions are rewritten using the conversation." },
  { icon: "eye", title: "Check the source", text: "Hover a number to see the passage. Click it to open the page with the text highlighted." },
] as const;

export default function Landing() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="page">
        <header className="nav">
          <Logo />
          <nav className="nav-links" aria-label="Main">
            <a className="opt" href="#how">
              How it works
            </a>
            <a className="opt" href="#evidence">
              Evidence
            </a>
            <a className="opt" href={REPO_URL}>
              GitHub
            </a>
            <ThemeToggle />
            <Link className="btn btn-secondary" href="/chat">
              Open the app
            </Link>
          </nav>
        </header>

        <main id="main">
          <section className="hero" aria-labelledby="hero-title">
            <div>
              <p className="eyebrow">Document Q&amp;A for legal PDFs</p>
              <h1 id="hero-title">Ask the contract. Get the page it came from.</h1>
              <p className="lede">
                Every answer links to the exact passage, highlighted on the page. If the documents don&apos;t say, Lexio tells you
                instead of guessing.
              </p>
              <div className="cta">
                <Link className="btn btn-primary btn-lg" href="/chat">
                  Try a sample contract <Icon name="arrow" />
                </Link>
                <SignInButton>Upload your own PDF</SignInButton>
              </div>
              <div className="try">
                <p className="muted small">No sign-in needed for the samples. Or start with a question:</p>
                <div className="row">
                  {SAMPLE_QUESTIONS.slice(0, 3).map((q) => (
                    <Link key={q} className="chip" href={`/chat?q=${encodeURIComponent(q)}`}>
                      {q}
                    </Link>
                  ))}
                </div>
              </div>
            </div>

            <figure className="demo" style={{ margin: 0 }} aria-label="Example answer">
              <div className="demo-q">Can the other party share my confidential information with its contractors?</div>
              <p className="demo-a">
                Yes, with limits. They may share it with employees, agents, advisors and contractors who have a reasonable need to
                know for the purpose<span className="cite on">1</span>. Those people must be bound by confidentiality duties no less
                protective, and the receiving party stays responsible for their compliance<span className="cite on">1</span>.
              </p>
              <div className="source-card">
                <header>
                  <span className="mono">Mutual NDA · page 2</span>
                  <span className="pill">
                    <Icon name="shield" />
                    Passage found
                  </span>
                </header>
                <div className="paper">
                  <p>
                    …(b) not disclose Confidential Information to third parties without the Disclosing Party&apos;s prior written
                    approval, except that the Receiving Party may disclose Confidential Information to{" "}
                    <mark>its employees, agents, advisors, contractors and other representatives having a reasonable need to know</mark>{" "}
                    for the Purpose, provided these representatives are bound by confidentiality obligations no less protective than
                    the applicable terms in this MNDA…
                  </p>
                </div>
              </div>
              <figcaption className="demo-cap">Example on the sample Mutual NDA (Common Paper, CC BY 4.0).</figcaption>
            </figure>
          </section>

          <section id="evidence" aria-labelledby="ev-title">
            <h2 id="ev-title" className="sr-only">
              Measured results
            </h2>
            <ul className="evidence">
              {EVIDENCE.map((e) => (
                <li key={e.big}>
                  <b>{e.big}</b>
                  <span>{e.text}</span>
                </li>
              ))}
            </ul>
            <p className="evidence-note">
              From the project&apos;s own answer evaluation, with confidence intervals and the method written up in the{" "}
              <a href={`${REPO_URL}/blob/main/backend/evals/results/answers-gemini.md`}>repository</a>.
            </p>
          </section>

          <section id="how" className="how" aria-labelledby="how-title">
            <div>
              <p className="eyebrow">How it works</p>
              <h2 id="how-title">Verify in one click, not one hour.</h2>
            </div>
            <ol className="steps">
              {STEPS.map((s) => (
                <li key={s.title} className="step">
                  <span className="ico">
                    <Icon name={s.icon} />
                  </span>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>
          </section>
        </main>

        <footer className="footer">
          <span>Built with FastAPI, Postgres + pgvector and Next.js. Open source.</span>
          <span>
            Not legal advice. Sample documents are public; sources and licences are in the{" "}
            <a href={`${REPO_URL}/blob/main/data/samples/NOTICE.md`}>notice</a>.
          </span>
        </footer>
      </div>
    </>
  );
}

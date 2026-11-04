import type { Metadata } from "next";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { REPO_URL } from "@/lib/samples";

export const metadata: Metadata = {
  title: "Privacy policy",
  description: "What Lexio stores, who it is shared with, how long it is kept, and how to delete it.",
  alternates: { canonical: "/privacy" },
};

const UPDATED = "4 November 2026";
const CONTACT = `${REPO_URL}/issues`;
const OPERATOR = "https://github.com/rumanmlk";

export default function Privacy() {
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <div className="page">
        <header className="nav">
          <Logo />
          <nav className="nav-links" aria-label="Main">
            <ThemeToggle />
            <Link className="btn btn-secondary" href="/chat">
              Open the app
            </Link>
          </nav>
        </header>

        <main id="main" className="legal">
          <p className="eyebrow">Legal</p>
          <h1>Privacy policy</h1>
          <p className="muted">Last updated {UPDATED}</p>

          <p>
            Lexio is a free, open-source demo that answers questions about PDF documents and shows the page each answer came from.
            It is run by an individual, not a company: <a href={OPERATOR}>rumanmlk</a> on GitHub, who is responsible for
            the data described here. This page says what the app actually does with data, in plain words. If the
            app changes, this page changes with it.
          </p>

          <div className="callout" role="note">
            <b>Do not upload sensitive documents.</b> Text from a PDF you upload is sent to Google&apos;s Gemini API to be indexed,
            and parts of it are sent to Groq when you ask a question. Both are services outside this project (see{" "}
            <a href="#sharing">who receives data</a>). Upload only documents you are comfortable sharing with them, such as public
            contracts and templates.
          </div>

          <div className="callout" role="note">
            <b>Slightly different in the EEA, Switzerland and the UK.</b> Google&apos;s Gemini API terms allow only its paid
            service to be used for users in these regions, and this demo runs on the free service. So for visitors detected in
            these countries (the country is read from your connection when you make a request and is not stored), uploading
            documents is turned off and nothing you type is ever sent to Gemini. You can still ask your own questions about the
            sample documents: they are searched by keyword matching in the database instead of the AI-assisted search, and
            the question goes to Groq twice: once to write a short hint that improves the keyword search, and once, with the
            matching public sample passages, to write the answer. The suggested questions
            use search data computed in advance, so they get the full search. The source code and evaluation results in the{" "}
            <a href={REPO_URL}>repository</a> are open to everyone.
          </div>

          <h2 id="summary">The short version</h2>
          <ul>
            <li>The sample documents work without an account, and no account details are collected for them.</li>
            <li>
              If you sign in with Google, the app keeps only an anonymous Google account ID. It does not store your name, email
              address or picture.
            </li>
            <li>PDFs you upload are visible only to your account, and you can delete them, or everything, at any time.</li>
            <li>
              There are no advertising or analytics trackers, no automated decisions about you and no profiling, and no data is
              sold or shared for advertising.
            </li>
          </ul>

          <h2 id="collect">What is collected</h2>
          <h3>Visiting without an account</h3>
          <p>
            To keep the free demo inside its daily limits, the server counts questions and uploads per visitor. It does this using a
            keyed hash of your IP address. The IP address itself is not stored, and without the secret key held by the server the hash cannot be turned back into it. These
            counters are deleted automatically after 7 days. The sample documents are public and shared by everyone.
          </p>

          <h3>Signing in with Google</h3>
          <p>
            Sign-in uses Google and asks for the basic <code>openid</code>, <code>email</code> and <code>profile</code> permissions.
            Google sends the app your name, email address and picture during sign-in, but the app does not save them. It saves
            your Google account ID (an opaque number) in an encrypted session cookie and uses it to decide which documents are
            yours. It does not use Google user data for anything else, does not share it with anyone, and does not use it for
            advertising or to train models. The use of information received from Google APIs follows the{" "}
            <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>,
            including its Limited Use requirements.
          </p>

          <h3>Documents you upload</h3>
          <p>When you upload a PDF while signed in, the app stores:</p>
          <ul>
            <li>the original PDF file, so you can view the cited page (in private object storage);</li>
            <li>the file name, size, page count and a fingerprint (SHA-256) used to detect duplicate uploads;</li>
            <li>
              the text of the PDF split into passages, together with a numeric embedding of each passage that makes it searchable.
            </li>
          </ul>
          <p>
            They are tied to your account ID and are not visible to other users. Uploaded files are limited in size and number per
            account.
          </p>

          <h3>Your questions</h3>
          <p>
            Questions and answers are processed to produce a reply, and the conversation is kept only in your browser tab. The
            server does not store your questions or the answers. The app can send performance traces (timings and counts, not the
            text of questions or answers) to Langfuse, but this is switched off unless the operator turns it on, and it is off
            at the time of writing.
          </p>

          <h3>Cookies and browser storage</h3>
          <ul>
            <li>
              <b>Sign-in cookies</b> (set only when you sign in): an encrypted session cookie and short-lived security cookies from
              Auth.js. They are strictly necessary for being signed in. The session cookie lasts up to 30 days of inactivity and is
              removed when you sign out. The security cookies used during the sign-in step (including a CSRF token) expire when
              you close your browser, or after 15 minutes for the ones that carry the sign-in handshake.
            </li>
            <li>
              <b>Theme choice</b>: your light or dark preference is saved in your browser&apos;s local storage. It never leaves
              your device.
            </li>
          </ul>
          <p>
            Nothing else is saved on your device. There are no advertising or analytics cookies, and fonts and scripts are served
            from this site itself, so your browser does not contact Google Fonts or any other third party just to show a page.
            Because only strictly necessary storage is used, there is no cookie banner.
          </p>

          <h2 id="sharing">Who receives data</h2>
          <p>The app relies on a few services. They receive only what is needed for their part:</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Service</th>
                  <th scope="col">What it receives</th>
                  <th scope="col">Why</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Google Gemini API</th>
                  <td>
                    Text passages of documents you upload, and your questions (to find matching passages). Nothing from visitors
                    in the EEA, Switzerland and the UK
                  </td>
                  <td>Creating search embeddings</td>
                </tr>
                <tr>
                  <th scope="row">Groq</th>
                  <td>Your question, recent conversation turns and the passages found for it</td>
                  <td>Writing the answer</td>
                </tr>
                <tr>
                  <th scope="row">Google Sign-In</th>
                  <td>Your sign-in request</td>
                  <td>Authentication</td>
                </tr>
                <tr>
                  <th scope="row">Vercel</th>
                  <td>All requests to the site and the API, and uploaded PDFs (Vercel Blob)</td>
                  <td>Hosting and file storage</td>
                </tr>
                <tr>
                  <th scope="row">Neon</th>
                  <td>The database described above (hosted in the AWS US East region)</td>
                  <td>Storing passages, embeddings and counters</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p>
            <b>Google Gemini.</b> The Gemini API is used on its free tier. Under Google&apos;s{" "}
            <a href="https://ai.google.dev/gemini-api/terms">Gemini API terms</a>, content sent to unpaid services may be used by
            Google to provide, improve and develop its products and machine-learning technologies, and human reviewers may read
            and annotate it (after it is disconnected from your Google account and the operator&apos;s API key and project).
            Google asks that you do not submit sensitive, confidential or personal information to these services. This is why you
            should upload only documents you are happy to share. For users in the EEA, Switzerland and the UK, Google allows only
            its paid service, which is why nothing from those visitors is sent to Gemini (see the notice at the top).
          </p>
          <p>
            <b>Groq.</b> According to <a href="https://console.groq.com/docs/your-data">Groq&apos;s data documentation</a>, Groq does
            not retain inference inputs and outputs by default, but may log them for up to 30 days to troubleshoot errors or
            investigate abuse. Its <a href="https://console.groq.com/docs/legal/services-agreement">services agreement</a> says
            Groq may not use inputs or outputs to train or fine-tune models without the customer&apos;s permission, and this
            project gives no such permission.
          </p>
          <p>
            <b>Hosting.</b> Vercel and Neon process data on the operator&apos;s behalf. Vercel keeps runtime logs of requests, which
            can include IP addresses, for 1 hour on Vercel&apos;s free plan, which this demo uses (see its{" "}
            <a href="https://vercel.com/docs/logs/runtime">runtime logs documentation</a>). Neon keeps a short change history so
            that a database can be restored; on the free plan this is 6 hours (see its{" "}
            <a href="https://neon.com/docs/postgres/backup-restore/history-window">history window documentation</a>). Because
            these services run in the United States and other countries, data may be transferred outside your country.
          </p>
          <p>Data is not sold, rented or shared for advertising. It is disclosed otherwise only if the law requires it.</p>

          <h2 id="retention">How long data is kept</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Data</th>
                  <th scope="col">Kept until</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">Uploaded PDFs, passages and embeddings</th>
                  <td>You delete the document or choose “Delete my data”</td>
                </tr>
                <tr>
                  <th scope="row">Uploads that failed or were never completed</th>
                  <td>Removed automatically about 2 hours later</td>
                </tr>
                <tr>
                  <th scope="row">Daily limit counters (keyed hash of your IP or account ID)</th>
                  <td>7 days</td>
                </tr>
                <tr>
                  <th scope="row">Session cookie</th>
                  <td>Until you sign out or it expires</td>
                </tr>
                <tr>
                  <th scope="row">Questions and answers</th>
                  <td>Not stored on the server</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p>
            Deleted data can remain in the database host&apos;s restore history for up to 6 hours, and in the other services for
            the periods given above, before it is gone completely. Anything a third-party service has already received follows
            that service&apos;s own rules.
          </p>

          <h2 id="rights">Your choices and rights</h2>
          <ul>
            <li>
              <b>Delete everything:</b> when signed in, choose “Delete my data” in the document panel. This removes your
              documents, files, passages and embeddings. Since nothing else about you is stored, there is nothing more to erase.
            </li>
            <li>
              <b>Delete one document:</b> use the delete button next to it.
            </li>
            <li>
              <b>Withdraw Google access:</b> remove Lexio from{" "}
              <a href="https://myaccount.google.com/connections">your Google account&apos;s connections</a>.
            </li>
            <li>
              <b>Other requests:</b> depending on where you live (for example under the GDPR or the California CCPA), you may have
              rights to access, correct or delete your data, to object to processing, and to complain to a data protection
              authority. The app holds so little about you that the delete options above cover almost every case; for anything
              else, <a href={CONTACT}>open an issue</a> and avoid putting personal details in it.
            </li>
          </ul>
          <p>
            Where the GDPR applies, the legal basis for processing is providing the service you asked for (contract) and keeping
            it secure and within its limits (legitimate interests).
          </p>

          <h2 id="other">Other things to know</h2>
          <ul>
            <li>
              Under California law (CCPA/CPRA), the app does not sell or share personal information for advertising, and collects
              only the categories described above: an account identifier, documents you upload, and technical data such as the
              hashed IP address used for limits.
            </li>
            <li>Lexio is not meant for children under 16, and the operator does not knowingly collect their data.</li>
            <li>
              Answers are produced by an AI model from the documents you choose. They can be wrong, and they are not legal advice.
            </li>
            <li>
              The source code is public at <a href={REPO_URL}>GitHub</a>, so you can check any statement on this page against what
              the app does.
            </li>
          </ul>

          <h2 id="contact">Contact and changes</h2>
          <p>
            Questions about this policy: <a href={CONTACT}>open an issue on GitHub</a>. When this policy changes, the date at the
            top is updated, and the history is visible in the repository.
          </p>
        </main>

        <footer className="footer">
          <span>
            <Link href="/">Home</Link>
          </span>
          <span>Not legal advice.</span>
        </footer>
      </div>
    </>
  );
}

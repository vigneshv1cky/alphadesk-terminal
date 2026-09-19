// The contributor licence agreement check (CLA.md, section 7).
//
// Runs from .github/workflows/cla.yml on every pull request and on every
// comment on one. It records a signature when someone comments the signing
// sentence, and marks the pull request's head commit with a "CLA" status:
// success once every person who authored a commit in it has signed.
//
// Signatures live in signatures.json on the `cla-signatures` branch, so the
// check never writes to main. One signature covers every later pull request
// from the same GitHub account.
//
// SECURITY: the workflow runs with a write token on pull requests from
// forks, so it must never run the contributor's code. This file is always
// read from the BASE branch, and it only reads comments and commit metadata
// through the API — nothing from the pull request is checked out or executed.

const SENTENCE =
  "I have read the AlphaDesk Contributor Licence Agreement, version 1.0, and I agree to it.";
const VERSION = "1.0";
const BRANCH = "cla-signatures";
const FILE = "signatures.json";
const MARKER = "<!-- alphadesk-cla -->";
// The copyright holder signs nothing to himself.
const EXEMPT = new Set(["vigneshv1cky"]);

/** Comparable form of a comment: quote marks from a copied blockquote,
 * spacing, case and a trailing full stop do not matter. */
function normalise(text) {
  return String(text || "")
    .replace(/^\s*>\s?/gm, "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/[.!]+$/, "")
    .toLowerCase();
}

function isSignature(body) {
  return normalise(body) === normalise(SENTENCE);
}

function isBot(login, type) {
  return type === "Bot" || /\[bot\]$/i.test(login || "");
}

/** Who must have signed: the pull request's author and the GitHub account
 * behind every commit, less the owner and bots. A commit whose email is
 * linked to no GitHub account cannot be matched to a signature, so its
 * author is listed separately and blocks the check until fixed. */
function requiredSigners(prUser, commits) {
  const logins = new Map();
  const unlinked = new Set();
  const add = (login, type) => {
    if (!login || isBot(login, type) || EXEMPT.has(login.toLowerCase())) return;
    logins.set(login.toLowerCase(), login);
  };
  add(prUser && prUser.login, prUser && prUser.type);
  for (const c of commits || []) {
    if (c.author && c.author.login) add(c.author.login, c.author.type);
    else {
      const who = (c.commit && c.commit.author) || {};
      unlinked.add(who.name || who.email || "an unknown author");
    }
  }
  return { logins: [...logins.values()], unlinked: [...unlinked] };
}

function unsigned(logins, signatures) {
  const signed = new Set((signatures || []).map(s => String(s.login).toLowerCase()));
  return logins.filter(l => !signed.has(l.toLowerCase()));
}

function commentBody(missing, unlinked, docUrl) {
  if (!missing.length && !unlinked.length) {
    return `${MARKER}\n**Contributor licence agreement:** everyone on this pull request has signed. Thank you.`;
  }
  const lines = [
    MARKER,
    `**Contributor licence agreement.** AlphaDesk is dual-licensed (AGPL-3.0 and a commercial licence), so every contributor signs the [CLA](${docUrl}) once. You keep the copyright in your work.`,
    "",
  ];
  if (missing.length) {
    lines.push(`Not yet signed: ${missing.map(l => `@${l}`).join(", ")}. To sign, post this as a comment on this pull request:`, "", "```", SENTENCE, "```", "");
  }
  if (unlinked.length) {
    lines.push(`Commits by ${unlinked.join(", ")} use an email address that is not linked to any GitHub account, so they cannot be matched to a signature. Add that address to your GitHub account (Settings → Emails), or re-author the commits, and push again.`);
  }
  return lines.join("\n");
}

async function readSignatures(github, owner, repo) {
  try {
    const { data } = await github.rest.repos.getContent({ owner, repo, path: FILE, ref: BRANCH });
    return { signatures: JSON.parse(Buffer.from(data.content, "base64").toString("utf8")), sha: data.sha };
  } catch (e) {
    if (e.status === 404) return { signatures: [], sha: null };
    throw e;
  }
}

async function ensureBranch(github, owner, repo, base) {
  try {
    await github.rest.repos.getBranch({ owner, repo, branch: BRANCH });
  } catch (e) {
    if (e.status !== 404) throw e;
    const { data } = await github.rest.git.getRef({ owner, repo, ref: `heads/${base}` });
    await github.rest.git.createRef({ owner, repo, ref: `refs/heads/${BRANCH}`, sha: data.object.sha });
  }
}

async function recordSignature(github, owner, repo, base, entry) {
  await ensureBranch(github, owner, repo, base);
  // Two signatures landing together conflict on the file's version; the
  // second re-reads and tries again.
  for (let attempt = 0; attempt < 3; attempt++) {
    const { signatures, sha } = await readSignatures(github, owner, repo);
    if (signatures.some(s => String(s.login).toLowerCase() === entry.login.toLowerCase())) return signatures;
    const next = [...signatures, entry];
    try {
      await github.rest.repos.createOrUpdateFileContents({
        owner, repo, path: FILE, branch: BRANCH, sha: sha || undefined,
        message: `CLA ${VERSION} signed by @${entry.login} (#${entry.pull_request})`,
        content: Buffer.from(JSON.stringify(next, null, 2) + "\n").toString("base64"),
      });
      return next;
    } catch (e) {
      if (e.status !== 409 && e.status !== 422) throw e;
    }
  }
  throw new Error("could not record the signature after three attempts");
}

async function upsertComment(github, owner, repo, number, body, onlyIfExists) {
  const comments = await github.paginate(github.rest.issues.listComments, { owner, repo, issue_number: number, per_page: 100 });
  const mine = comments.find(c => (c.body || "").startsWith(MARKER));
  if (mine) {
    if (mine.body !== body) await github.rest.issues.updateComment({ owner, repo, comment_id: mine.id, body });
  } else if (!onlyIfExists) {
    await github.rest.issues.createComment({ owner, repo, issue_number: number, body });
  }
}

async function run({ github, context, core }) {
  const { owner, repo } = context.repo;
  const payload = context.payload;
  if (context.eventName === "issue_comment" && !(payload.issue && payload.issue.pull_request)) return;
  const number = context.eventName === "issue_comment" ? payload.issue.number : payload.pull_request.number;

  const { data: pr } = await github.rest.pulls.get({ owner, repo, pull_number: number });
  const base = pr.base.ref;
  const docUrl = `https://github.com/${owner}/${repo}/blob/${base}/CLA.md`;
  const commits = await github.paginate(github.rest.pulls.listCommits, { owner, repo, pull_number: number, per_page: 100 });
  const required = requiredSigners(pr.user, commits);

  let { signatures } = await readSignatures(github, owner, repo);
  if (context.eventName === "issue_comment" && isSignature(payload.comment.body) && !isBot(payload.comment.user.login, payload.comment.user.type)) {
    signatures = await recordSignature(github, owner, repo, base, {
      login: payload.comment.user.login,
      id: payload.comment.user.id,
      version: VERSION,
      signed_at: payload.comment.created_at,
      pull_request: number,
      comment: payload.comment.html_url,
    });
    core.info(`recorded a signature from @${payload.comment.user.login}`);
  }

  const missing = unsigned(required.logins, signatures);
  const ok = !missing.length && !required.unlinked.length;
  await github.rest.repos.createCommitStatus({
    owner, repo, sha: pr.head.sha, context: "CLA", target_url: docUrl,
    state: ok ? "success" : "failure",
    description: (ok ? "Every contributor has signed the CLA" : `Not signed: ${[...missing, ...required.unlinked].join(", ")}`).slice(0, 140),
  });
  // A pull request only the owner and bots touched gets no comment at all;
  // an earlier request to sign is updated to say it is done.
  await upsertComment(github, owner, repo, number, commentBody(missing, required.unlinked, docUrl), ok);
  core.info(ok ? "CLA: all signed" : `CLA: missing ${missing.join(", ") || "-"}; unlinked ${required.unlinked.join(", ") || "-"}`);
}

module.exports = { SENTENCE, MARKER, normalise, isSignature, requiredSigners, unsigned, commentBody, run };

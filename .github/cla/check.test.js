// node --test .github/cla — the pure parts of the CLA check.
const test = require("node:test");
const assert = require("node:assert");
const cla = require("./check.js");

test("the signing sentence is recognised however it is pasted", () => {
  assert.ok(cla.isSignature(cla.SENTENCE));
  assert.ok(cla.isSignature(`  > ${cla.SENTENCE.toUpperCase()}  `));
  assert.ok(cla.isSignature(cla.SENTENCE.replace(/\.$/, "")));
  assert.ok(cla.isSignature(cla.SENTENCE.replace(/ /g, "\n")));
  assert.ok(!cla.isSignature("I agree"));
  assert.ok(!cla.isSignature(`${cla.SENTENCE} But not really.`));
  assert.ok(!cla.isSignature(""));
});

test("the author and every commit's account must sign; owner and bots never", () => {
  const commits = [
    { author: { login: "alice", type: "User" }, commit: { author: { name: "Alice" } } },
    { author: { login: "Bob", type: "User" }, commit: { author: { name: "Bob" } } },
    { author: { login: "vigneshv1cky", type: "User" }, commit: { author: { name: "V" } } },
    { author: { login: "dependabot[bot]", type: "Bot" }, commit: { author: { name: "dependabot" } } },
    { author: null, commit: { author: { name: "Carol", email: "carol@example.com" } } },
    { author: null, commit: { author: { name: "V", email: "MuruganVignesh0810@gmail.com" } } },
  ];
  const r = cla.requiredSigners({ login: "alice", type: "User" }, commits);
  assert.deepStrictEqual(r.logins.sort(), ["Bob", "alice"]);
  assert.deepStrictEqual(r.unlinked, ["Carol"]);
  assert.deepStrictEqual(cla.requiredSigners({ login: "vigneshv1cky", type: "User" }, commits.slice(2, 4)),
    { logins: [], unlinked: [] });
});

test("signatures match accounts regardless of case", () => {
  assert.deepStrictEqual(cla.unsigned(["alice", "Bob"], [{ login: "ALICE" }]), ["Bob"]);
  assert.deepStrictEqual(cla.unsigned(["alice"], []), ["alice"]);
});

test("the comment names who is missing and how to sign", () => {
  const body = cla.commentBody(["alice"], ["Carol"], "https://x/CLA.md");
  assert.ok(body.startsWith(cla.MARKER));
  assert.ok(body.includes("@alice") && body.includes(cla.SENTENCE) && body.includes("Carol"));
  assert.ok(cla.commentBody([], [], "u").includes("has signed"));
});

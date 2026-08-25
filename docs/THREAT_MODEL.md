# Threat model

Written so that a reader can disagree with it. Every control in the codebase
should trace back to a row here; anything here with no control is an accepted
risk, and says so.

## What is being protected

The user's machine and the data on it: source code, credentials, the rest of the
filesystem, and the network the machine can reach.

## Who might attack it

**A1 — Content the model reads.** A web page, a README, a dependency's output, a
CI log. This is the likeliest attacker by a wide margin, because it needs no
access to anything: it only needs to be read. It can propose any tool call.

**A2 — Someone who learns the tunnel URL.** Guessed, leaked, or found in a
screenshot. They can reach the MCP endpoint and the consent page.

**A3 — A malicious repository.** The user clones it and authorises it as a
workspace. It controls `package.json`, `.git/hooks`, lockfiles, and every file
the model will read.

**A4 — Another process on the same machine**, running as the same user.

**A5 — The model itself**, confused rather than malicious: a mistaken `rm`, a
patch applied to the wrong file, a dev server left running.

Out of scope: an attacker with the machine's console or root, a compromised
OpenAI, and a compromised Python package supply chain.

## What each one could try, and what stops it

| # | Attack | Attacker | Control | Residual risk |
|---|---|---|---|---|
| 1 | Inject an instruction into a page so the model runs a command | A1 | Tiers: destructive commands refused outright; anything unlisted asks, outside the chat, showing the literal command | The owner may approve without reading. Rate limiting exists because fatigue is the real failure |
| 2 | Read `~/.ssh/id_rsa` through `read_file` | A1, A5 | Path jail: resolve before containment; credential names denied | — |
| 3 | Read it through `search` instead | A1 | Search applies the same rules | — |
| 4 | Read it through the browser as `file://` | A1 | URL check runs the same jail; other schemes refused | **Found by reviewing the finished code, not by design.** See §Known gaps |
| 5 | Escape with a symlink or junction inside the workspace | A1, A3 | Resolution happens before the containment check | A path could change between the check and the open; the file tools are the second gate |
| 6 | Hide `rm -rf` behind `&&`, `$( )`, or `powershell -EncodedCommand` | A1 | Full command parsing, every segment judged, encoded payloads decoded | A payload in a language we cannot parse stays EXEC_OTHER: unreadable is not treated as safe |
| 7 | Put the payload in `package.json` so `npm test` runs it | A3 | The script's own text is what gets classified | The script can still call something whose behaviour we cannot see |
| 7b | Escape the host through a container: `docker run -v /:/host`, `--privileged`, or the Docker socket | A1, A5 | Refused outright; mounts of credential directories refused by name, since `$HOME/.ssh` is never expanded | A container runtime not in the recognised set |
| 7c | Run a destructive command inside a container | A1 | The inner command of `run`/`exec`/`create` is pulled out and judged on its own | An inner command in a language the parser cannot read |
| 7d | Destroy a database volume | A1, A5 | `volume rm`, `prune --volumes` and `down -v` refused: the journal has never covered volumes | A migration that corrupts data without deleting anything — see below |
| 8 | Use the tunnel URL directly | A2 | OAuth required; no unauthenticated mode exists | — |
| 9 | Approve their own connection at the consent page | A2 | Pairing code printed on the machine's console; five wrong guesses lock it | An attacker can lock out the owner. Accepted: `ph auth rotate` clears it |
| 10 | Steal a refresh token | A2 | Single use; rotation makes reuse visible | The window before the next refresh |
| 11 | Exfiltrate a secret in tool output | A1 | Redaction on the way out; credential files unreadable in the first place | An unrecognised secret format. Redaction is a net, not the wall |
| 12 | Reach an internal service or cloud metadata | A1 | Every address resolved and checked, before each redirect; local addresses refused entirely | DNS rebinding between check and connect — bounded by the host having to be allowlisted first |
| 13 | Drive the console from another machine | A2, A4 | Loopback only, plus a token | Another local process could read the token from the console URL |
| 14 | Quietly rewrite the audit log | A1, A3 | Hash chain makes edits and deletions detectable | Detection, not prevention |
| 15 | Turn off the guards | A1 | No tool can reach the config or the journal | — |
| 16 | Lose work by overwriting it | A5 | Every write journaled; undo is itself journaled | — |
| 17 | Leave a dev server running | A5 | Process tree tracked; the stop button ends everything | — |
| 18 | Inherit an API key into a child process | A1 | Environment built from an allowlist; loader variables never forwarded | — |

## Known gaps, stated rather than implied

- **Row 4 was a real hole**, closed only after the code was written: `file://`
  counted as a local address, so the browser could open and report any file on
  the machine. It is worth recording because it shows the shape of the risk —
  a boundary enforced in one tool and forgotten in another.
- **Rows 5 and 12 are time-of-check gaps.** Both are narrowed rather than
  closed, and both need a filesystem or socket API that pins what was checked.
- **Row 1 has no technical answer** beyond making the prompt honest and rare.
  A person who approves everything is not protected by anything here.
- **Database state has no undo.** The journal keeps pre-images of files. A
  migration run inside a container changes something it has never covered, so
  "put it back" does not apply. Refusing to delete volumes limits the damage;
  it does not make a bad migration reversible. Anyone relying on this for
  schema work should be taking their own backups.
- **Phase 2 would widen this considerably.** Screen capture, input synthesis and
  Office automation reach outside any workspace by their nature, and this model
  needs rewriting before that work starts, not after.

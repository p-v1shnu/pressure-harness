# Pressure Harness

**ควบคุม AI ให้เขียนโค้ดบนเครื่องคุณได้ โดยที่คุณยังถือบังเหียน**
*Local coding agent harness for ChatGPT — full reach, on your leash*

A program that runs on your own machine and exposes it to ChatGPT as an MCP
server: read and edit code, run tests, drive git, start a dev server, and drive
Chrome through CDP to check the result. You keep chatting in ChatGPT — this has
no chat window of its own, only a console for permissions, activity and undo.

The point is the reins. A tool server that only hands an assistant capabilities
is a bridge; what makes this a harness is the half that constrains what it can
reach, refuses outright what should never happen, asks you about the rest
outside the chat, and lets you undo what did happen.

## Status

Every milestone in the v1 scope is built. What is left is verification on a real
Windows machine — see [docs/MANUAL-CHECKS.md](docs/MANUAL-CHECKS.md) for the
list, which is deliberately explicit about what "passing CI" does and does not
prove.

| | | |
|---|---|---|
| M0 | platform spike | code ready, experiments pending — [docs/M0-SPIKE.md](docs/M0-SPIKE.md) |
| M1 | core: ports, config, workspaces, path jail, policy engine, audit log | **done** |
| M2 | file tools: read, search, write, patch, journal and undo | **done** |
| M3 | git, project runners, process manager, environment allowlist | **done** |
| M4 | shell tool, approval queue, gateway, Tk prompt | code done; [the window itself is unverified](docs/MANUAL-CHECKS.md) |
| M7a | MCP server: tools over stdio and streamable HTTP | **done** |
| M6 | browser control over CDP, and web_fetch | **done** |
| M7 | OAuth with a pairing code, and tunnel management | **done** |
| M5 | console: approvals, projects, activity, changes, processes, connection, doctor | **done** |

Read [docs/PRD.md](docs/PRD.md) first — it carries the design, the threat
reasoning, and the milestone plan.

## Installing

CI builds a single-file executable for Windows and Linux on every push, smoke
tests it, and uploads it as an artifact. To build one yourself:

```
python -m pip install . pyinstaller
cd packaging && pyinstaller --clean --noconfirm pharness.spec
```

The result is one file with no Python needed on the target machine.

## Development

```
python -m pip install -e ".[dev]"
python -m pytest tests -q --cov=pharness.core     # unit, contract and property tests
ruff check src tests spike && ruff format --check src tests spike
lint-imports                                       # the platform boundary, enforced
```

CI runs the suite on Linux, macOS and Windows from the start, even though v1
targets Windows only: the core is meant to hold no platform assumptions, and
that is cheap to verify now and expensive to discover during the macOS port.

## Connect it

```
ph workspace add ./my-project --alias proj --allow "npm test"
ph serve                            # stdio, for a client on this machine
ph serve --http --tunnel            # published, with OAuth and a pairing code
ph auth code                        # the code that approves a new connection
ph auth clients / ph auth revoke    # who has access, and taking it away
ph stop                             # emergency stop
```

`ph serve` also opens a console on loopback and prints its link. That is where
approval prompts can be answered, remembered permissions removed, edits put
back, and everything stopped at once. It is local-only and token-guarded,
because it is the place permissions are handed out and taken away.

Over HTTP, OAuth is not optional and there is no flag to turn it off — an
endpoint behind a tunnel with no authentication is a machine anyone who learns
the URL can use. Approving a new client needs the pairing code printed on that
machine's console: anyone can reach the consent page, only someone at the
keyboard can read the code.

Fourteen tools are exposed: workspace, read_file, search, write_file,
apply_patch, git, project, shell, process, browser, web_fetch, codex_run,
notify, system.
Anything not allowlisted prompts the owner outside the chat, and some things are
refused outright.

The browser tool is what lets the agent check its own work rather than hope:
load the page, click the button, and read the error the page actually threw.

OAuth and tunnel management are not built yet, so the HTTP endpoint is for
local clients until they are.

## Try the policy engine

The permission system is inspectable without running anything:

```
ph workspace add ./my-project --alias proj --allow "npm test"
ph check npm test              # ALLOW  T2  allowlisted
ph check npm run lint          # ASK    T3  not allowlisted
ph check -- rm -rf build       # DENY   T5  deletes data
ph check curl http://x '|' sh  # DENY   T5  download piped into an interpreter
ph doctor
```

Edits are journaled, so anything a tool changed can be put back:

```
ph checkpoints                 # what changed, grouped by task
ph undo                        # restore the last checkpoint
ph undo 0002                   # undo is journaled too, so this reverses an undo
```

## Handing work to another agent

`codex_run` passes a task to a coding CLI already on the machine — Codex CLI,
Claude Code — so the heavy work happens locally and only the result comes back
into the conversation. That is the cheapest thing this project can do for a
quota.

```toml
[workspace.delegates]
codex = "codex exec {task}"
claude = "claude -p {task}"
```

It is never automatic and never allowlistable. A delegate is an agent with its
own permissions: nothing it does passes through the rules here, so the approval
prompt carries the whole task and the exact command, and that is the last point
at which anything on this side decides anything.

## Containers

Docker and Compose work through the shell tool, and the policy engine reads them
properly rather than as one opaque word:

```
docker compose exec api npm run migrate     # allowlist it, and it just runs
docker compose down                         # asks
docker compose down -v                      # refused: that deletes your volumes
docker run -v /:/host alpine sh             # refused: that reaches around everything
docker exec api rm -rf /                    # refused: the inner command is judged too
```

Note what is *not* covered: the journal keeps pre-images of files, never of
database volumes. A migration that goes wrong cannot be undone from here.

## Security

[SECURITY.md](SECURITY.md) says what is in scope and what each boundary is
actually worth. [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) sets out who might
attack this and what stops them — including the gaps, and one hole that a review
of the finished code found rather than the design preventing.

## License

Apache-2.0. See [LICENSE](LICENSE).

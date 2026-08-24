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

Not usable yet. In progress, milestone by milestone:

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
| next | console UI | not started |

Read [docs/PRD.md](docs/PRD.md) first — it carries the design, the threat
reasoning, and the milestone plan.

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

Over HTTP, OAuth is not optional and there is no flag to turn it off — an
endpoint behind a tunnel with no authentication is a machine anyone who learns
the URL can use. Approving a new client needs the pairing code printed on that
machine's console: anyone can reach the consent page, only someone at the
keyboard can read the code.

Thirteen tools are exposed: workspace, read_file, search, write_file,
apply_patch, git, project, shell, process, browser, web_fetch, notify, system.
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

## License

Apache-2.0. See [LICENSE](LICENSE).

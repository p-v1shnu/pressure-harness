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
| M2+ | file tools, git, processes, approvals, console UI, browser, transport | not started |

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

## License

Apache-2.0. See [LICENSE](LICENSE).

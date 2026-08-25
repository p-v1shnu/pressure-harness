# Security

Pressure Harness gives a language model reach into a real machine. That is the
product, so the interesting question is never "can it do things" but "what
cannot it do, and who decides".

## Reporting a vulnerability

Open a private security advisory on the repository, or email the maintainer.
Please do not open a public issue for anything exploitable.

Useful in a report: what an attacker controls, what they gain, and the smallest
sequence that shows it. A working proof against a default configuration is worth
more than a category name.

## What is in scope

Anything that lets an attacker reach past the boundaries below:

- reading or writing outside an authorised workspace, by any route
- running a command the policy engine should have refused or asked about
- getting an approval without the owner giving one
- reaching the MCP endpoint without a valid token, or the console from off-machine
- credentials leaving the machine: in tool output, in the audit log, in an error
- turning a page's content into an instruction the model acts on

## What is not

- the model doing something unwise that it was *allowed* to do; that is a
  permissions decision, not a vulnerability
- a workspace deliberately authorised over a whole drive, after the warning
- an attacker who already has the machine's console: the pairing code, the audit
  log and the config are all readable there by design

## Boundaries, and what each one is worth

| Boundary | Holds against | Does not hold against |
|---|---|---|
| Path jail | any path a tool is given, including symlinks and junctions | a workspace authorised too broadly |
| Command scanner | compound, substituted and interpreter-wrapped commands | code inside an interpreter payload it cannot parse — those are refused or asked about instead |
| Approval prompt | a model asking for something it should not | someone at the keyboard approving without reading |
| Pairing code | anyone who reaches the consent page through the tunnel | someone who can see the machine's screen |
| Console (loopback + token) | anything off the machine | another process running as the same user |
| Redaction | known credential shapes on the way out | an unknown secret format; the jail is the real defence |

## Dependencies

Locked to exact versions and to the hash of each file, in `requirements/*.lock`.
CI installs with `--require-hashes`, checks the locks still match
`pyproject.toml`, runs `pip-audit` against runtime and dev trees, and publishes
a CycloneDX SBOM built from the lock rather than from an installed environment,
so the same commit always yields the same inventory.

CI actions are pinned to commit SHAs rather than tags, since a tag is a label
its publisher can move, and Dependabot raises a pull request when a pin falls
behind so that pinning does not turn into staleness.

Released executables carry a SHA256 so you can check the file you have is the
file CI produced. They are deliberately not code-signed: this is distributed
within a circle who already know its author, so identity comes from how the file
reached you rather than from a certificate. That is a scope decision, and it
would need revisiting if the project were ever published openly.

The checksum only helps if it reaches you by a different route than the file
did. Sent together in one chat, it proves nothing to anyone who has that chat.

## Deliberate design decisions

- **HTTP always requires OAuth.** There is no flag to disable it. For an
  unauthenticated local connection, use stdio.
- **Approval happens outside the conversation.** What the model asks for and
  what the owner sees arrive through different channels on purpose.
- **An approval is bound to a payload hash**, never to a tool or a description.
- **Unattended means refused.** Every prompt expires; nothing waits forever.
- **There is no delete tool**, and every write is journaled so it can be undone.

# AI / Coding-Assistant Usage

## Tools used

The team used GitHub Copilot in VS Code as a coding and review assistant. It
was used to inspect the starter repository and assignment requirements,
suggest implementation approaches, review protocol and state-management
logic, help identify edge cases, and assist with documentation and report
editing. The team members read, tested, and adapted all generated suggestions;
the assistant was not treated as an authority for experimental results.

## One useful suggestion

One useful suggestion was to represent a client's reconnect position as the
latest finalized `(segment, revision)` watermark rather than the latest
provisional revision received. This matched the protocol's finalized-caption
recovery semantics and helped prevent provisional state from causing incorrect
HISTORY requests. We verified the decision by reading the protocol examples,
implementing it in the server and browser client, and running the history,
reconnect, and full unit-test suites.

## One suggestion that was wrong, inefficient, or required modification

An early suggestion treated the initial T5 measurements as valid even though
the network impairment had not actually been applied. The measurements were
therefore removed rather than reported. T5 was rerun only after verifying the
active `tc/netem` delay, jitter, and loss configuration, and the final report
now states honestly that the measured final completeness was 97.06%, below the
99% target.

## Responsibility statement

We understand that the team remains responsible for the submitted code, experimental results, and claims, and that every member may be asked to explain or modify relevant code during the viva.

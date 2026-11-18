# Local research workflow

Use this workflow to turn a research idea into a locally runnable task without
GitHub Discussions, the private RSI-Skills worker, or a publication account.
The wrapper manages local approval and validation records. The included
[RSI-Harness](../RSI-Harness/) still compiles tasks, runs the containers and
agents, and records results. Neither the wrapper nor an agent approves its own
work.

## Which conversations should I open?

Copy the three launch prompts from the [repository homepage](../README.md).
Their detailed role instructions are in [PROMPTS.md](PROMPTS.md).

Normally open **three separate conversations**. If you review the proposal
yourself, open only the first and third.

| Conversation | Give it | Take away |
| --- | --- | --- |
| Proposal | Your research question, baseline, and constraints | A filled-in `proposal.toml`. If the review asks for changes, return here. |
| Independent review | The proposal, without the previous conversation | Review notes and an approve/revise recommendation. Record your decision with `review`. |
| Task authoring | The brief printed by `author`, plus the Harbor task-creation skill | A Harbor template and a separate negative control. This conversation may see the formal tests and reference solution. |

Then run `build → validate → run` in the terminal. **Do not open a fourth
conversation for optimization:** `run` starts the optimizer through
RSI-Harness without carrying over the task author's conversation.

## Where files live

The `local-research` branch keeps the existing Harness and its regression
checks, without the public task collection or GitHub contribution automation.
Those remain available from [upstream OpenRSI Index](https://github.com/OpenRSI-Foundation/OpenRSI-Index).

```text
OpenRSI-Index/
├── RSI-Harness/                           # original runtime and tests
├── .github/workflows/                     # Harness regression checks only
└── local-research/                        # new local workflow
    ├── README.md
    ├── research.py                        # proposal through run
    ├── harness.py                         # adapter to the existing runtime
    ├── test_*.py
    └── examples/cpu-sequence/             # example proposal, template, negative control
```

Each experiment has a separate directory of your choosing. For example,
`./my-research/` accumulates these files as you run the commands:

```text
my-research/
├── proposal.toml          # your experiment design
├── review.json            # decision and notes bound to that proposal
├── build/
│   ├── task/              # packaged Harbor task
│   ├── negative-solve.sh  # kept outside the task package
│   └── manifest.json      # locked input hashes
├── validation.json        # latest validation status for this build
├── validation-runs/       # positive and negative control evidence
├── research-runs/         # optimizer runs and native Harness logs
└── .harness-data/         # local Harness runtime data
```

These are local workspace outputs, not additions to the upstream public task
catalog. Keep private experiment files out of commits.

## Setup

Run the commands below from the repository root. Drafting, recording a review,
and packaging use only Python 3.11+ standard library. For validation and runs,
use Python 3.12, `uv`, and a Linux host with a working Docker setup and the
permissions required by [RSI-Harness](../RSI-Harness/README.md). GPU tasks also
need the NVIDIA runtime and the declared hardware. A CPU task does not need a
GPU. For Codex use `RSI_AGENT_API_KEY` and, if applicable,
`RSI_AGENT_API_BASE_URL`; the wrapper does not expose the Harness local-login
flag. Keep credentials out of the project files. Local orchestration does not
imply offline operation: images may be pulled and the agent may call its provider.

```sh
uv sync --frozen --project RSI-Harness
uv run --project RSI-Harness rsi-harness --help
```

`uv run --project RSI-Harness python` in the examples below runs the wrapper
with the installed `rsi-harness` on its PATH. Consult the Harness documentation
for Docker privileges and authentication; a Docker client alone is not enough.

## 1. Write and review the experiment

```sh
python3 local-research/research.py propose ./my-research
```

Edit `my-research/proposal.toml`: define the research question, traceable
baseline, paths the optimizer may change, fixed evaluation and success
criteria, and budget. If the baseline refers to code or an artifact, pin an
immutable revision. Keep exploratory notes separate from the proposal.

Have an independent reviewer read that proposal. Ask them to check whether the
workload and budget answer the question, what the agent can change, whether the
score rewards the intended result, and whether an invalid candidate can pass.
Save the review to a file; then record the actual review decision:

```sh
python3 local-research/research.py review ./my-research \
  --decision approve --notes ./review-notes.md
```

Use `--decision revise` if the reviewer wants changes. The wrapper records an
explicit decision bound to the SHA-256 of the exact proposal bytes. An approval
cannot silently carry forward to a changed proposal. The CLI records a
decision; it does not establish the reviewer's identity or independence.

## 2. Author, then package a Harbor task

Generate a brief from the approved proposal:

```sh
python3 local-research/research.py author ./my-research >authoring-brief.md
```

In a separate authoring session, give a task-authoring agent that brief and the
[official Harbor task-creation skill](https://github.com/harbor-framework/skills/blob/main/skills/harbor-task-creator/SKILL.md).
Use the skill in the native agent session; this CLI does not fetch or invoke it.
Review the resulting template, including its fixed evaluator, candidate workspace,
and known-good oracle solution. Encode restrictions in the task and verifier,
not just in the proposal. Prepare a separate negative solution that makes a
deliberately invalid candidate, rather than simulating a verifier or environment
failure. The later optimization agent should not be the task author or reviewer.

```sh
python3 local-research/research.py build ./my-research \
  --template /path/to/harbor-task \
  --negative-solution /path/to/negative-solve.sh
```

Build packages the task locally and locks the inputs used by validation. The
negative solution stays separate from the optimizer's task. Proposal changes
require a matching new approval, and task amendments must be rebuilt and
validated rather than inheriting an earlier validation record.
Move the old `build/` directory aside before packaging a new version. The
negative control must live outside the task template.

## 3. Check both sides of the verifier

```sh
uv run --project RSI-Harness python local-research/research.py validate ./my-research
```

Validation is not just a file check. It compiles the task and runs both oracle
solutions through the actual Harness on local Docker. Both runs must yield
their declared sentinel values for the primary metric: the known-good candidate
must get the expected good score, and the deliberately invalid candidate must
get the expected negative-case score. A Docker failure, evaluator crash, or
missing score is not evidence that the invalid candidate was correctly rejected.
The tests are a minimum sanity check, not proof of scientific validity or a
guarantee against overfitting. Controls use the Harness single-final-Judge mode;
this checks the scoring path, not the multi-round agent feedback loop. For GPU
tasks pass the same `--gpus` selection to validation and to research runs.
Pin image digests and asset versions for real experiments, and revalidate
if these inputs, the Harness installation, or the host environment change.

## 4. Run the optimizer

```sh
uv run --project RSI-Harness python local-research/research.py run ./my-research --agent codex
```

Specify `--model MODEL` if needed, and `--gpus 0,1` (your actual allocation)
for a task requiring those GPUs. The wrapper checks the approved proposal,
locked task inputs and validation before invoking Harness. Inspect the native
Harness run directory for trajectories, metrics and failure diagnostics. The
workflow does not upload logs, submit a Discussion, or publish a task. The
local records protect against accidentally running stale inputs; they are not
a signature, an immutable audit log, or a defense against someone who can
rewrite the project directory.

## Small CPU example

The [CPU sequence smoke task](examples/cpu-sequence/) contains a model-free
proposal, a Harbor template (`template/`), and a separate
`negative-solve.sh`. Exercise the workflow with a fresh project directory:

```sh
example=local-research/examples/cpu-sequence
project=./cpu-sequence-run
python3 local-research/research.py propose "$project"
cp "$example/proposal.toml" "$project/proposal.toml"
```

Review the copied proposal and sample task, then record the independent
reviewer's decision using the command in step 1. After approval:

```sh
python3 local-research/research.py build "$project" \
  --template "$example/template" --negative-solution "$example/negative-solve.sh"
uv run --project RSI-Harness python local-research/research.py validate "$project"
```

The expected oracle scores are 1 and 0; no model credentials or GPUs are
needed for these checks. Docker is still required, and the first build may
need to pull the base image. If validation passes, you can optionally use the
command in step 4 with `"$project"` and an authenticated coding agent.

Run the workflow unit tests without Docker:

```sh
python3 -m unittest discover -s local-research -v
```

On a Linux host with Docker access and the installed Harness, the same suite
can run both controls over the real Docker backend:

```sh
RSI_LOCAL_DOCKER=1 RSI-Harness/.venv/bin/python -m unittest discover -s local-research -v
```

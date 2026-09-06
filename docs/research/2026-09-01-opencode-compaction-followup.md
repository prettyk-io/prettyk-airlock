# OpenCode compaction follow-up — 2026-09-01

## Status

The investigation confirms a configuration/runtime conflict, but does not yet
prove that GPT reasoning effort is the primary cause of the visible failure.
The Battlecruiser agent was then given the model-scoped `medium` variant for
Luna only. No global compaction or Supermemory setting was changed.

## Confirmed facts

- The project config has `compaction.auto: false` and loads
  `opencode-supermemory`.
- `.opencode/agent/battlecruiser.md` now selects `variant: medium`; this is
  scoped to the Battlecruiser agent using `openrouter/openai/gpt-5.6-luna-pro`
  and does not alter the project's default model or other agents.
- The cached plugin used by this workspace is `opencode-supermemory` 2.0.12.
  Its latest cached bundle still implements an independent path:
  token ratio → `session.summarize` → synthetic user `Continue`.
- The plugin uses `0.8` by default, obtains the context limit from the provider
  model metadata, and injects a synthetic `role: user` message containing
  `[COMPACTION CONTEXT INJECTION]` before calling `session.summarize`.
- The plugin source has no native `experimental.session.compacting` or
  `experimental.compaction.autocontinue` hook. NPM currently advertises 2.0.13,
  but the upstream main source and the locally cached 2.0.12 bundle retain the
  old path; upstream PR #70 remains open.
- The installed OpenCode SDK exposes the native hooks and the native compaction
  implementation restores the original session agent/model for auto-continue.
  The native implementation also selects the hidden `compaction` agent/model
  explicitly, avoiding the plugin's nearest-message race.
- The agent schema supports a separate `agent.compaction` configuration,
  `variant`, and provider-specific pass-through options. OpenCode's current
  documentation explicitly supports `reasoningEffort` as an agent/model option.
- The OpenCode config schema exposes native `compaction.auto`, `prune`,
  `tail_turns`, `preserve_recent_tokens`, and `reserved`; it does not expose a
  simple native percentage threshold.
- Runtime logs identify the recent desktop runtime as OpenCode 1.18.23. The
  command-line executable is not available on PATH, so a clean CLI A/B has not
  been run.

## Decision

The first intervention should target the compaction lifecycle, not prompt text
or more skills:

1. Let OpenCode own compaction and continuation (`compaction.auto: true`).
2. Ensure `agent.compaction` uses a model with a context window comparable to
   the active session model; for the Luna test, use the same Luna model and a
   low reasoning variant for the summary pass.
3. Suppress the legacy Supermemory trigger for the test by either removing the
   plugin for one clean control run or setting its effective threshold to `1`.
   `0` is not a valid disable value in the current plugin and silently falls
   back to `0.8`.
4. Keep the first run short and start it as a new session. Do not test by
   continuing the already-corrupted transcript.

## A/B protocol

### Run A — native OpenCode control

- New session, Luna model, native compaction enabled.
- Supermemory plugin absent for this run.
- Use a repeatable multi-step repository task long enough to cross the native
  compaction boundary.
- Record: model/variant, token counters, compaction event, compaction model,
  continuation model, whether the task resumes rather than emitting a summary
  to the user, and any runtime errors.

### Run B — native OpenCode plus memory retrieval/capture

- Same task shape and a fresh session.
- Native compaction enabled.
- Supermemory enabled for recall/capture, but its legacy trigger effectively
  suppressed (`compactionThreshold: 1`) until upstream PR #70 lands or a local
  native-hook replacement is installed.
- Compare the same measurements with Run A.

### Run C — reasoning check

- Repeat Run B with the main Luna agent's reasoning variant reduced one step
  (prefer `medium` or `low`, depending on the currently exposed model variants).
- Do not change compaction lifecycle and reasoning in the same first run; this
  isolates whether reasoning footprint changes the failure rate.

DeepSeek remains a control model, not a proposed replacement for the Luna
planning route.

## Acceptance criteria

The lifecycle hypothesis is accepted if a fresh Luna session completes the
same long task after native compaction while:

- the continuation is sent using the original session agent/model;
- no synthetic Supermemory compaction message is used as the trigger;
- no internal compaction summary is surfaced as the user-facing answer;
- the session does not remain on the hidden compaction agent;
- the run leaves a compact, usable context for the next step.

If Run A passes and Run B fails, the remaining defect is in the Supermemory
integration. If both fail, investigate OpenCode/OpenRouter model handling and
reasoning/output budgets next. If both pass but Run C changes behaviour, then
reasoning effort is a contributing factor rather than the root lifecycle bug.

## References

- `D:\prettyk-airlock\opencode.json`
- `D:\prettyk-airlock\.opencode\agent\battlecruiser.md`
- `D:\Infra\OpenCode\config\opencode\supermemory.jsonc`
- `D:\Infra\OpenCode\cache\opencode\packages\opencode-supermemory@latest\node_modules\opencode-supermemory\dist\index.js`
- `D:\Infra\OpenCode\share\opencode-home\node_modules\@opencode-ai\sdk\dist\v2\gen\types.gen.d.ts`
- `D:\Infra\OpenCode\share\opencode\log\opencode.log`
- https://github.com/supermemoryai/opencode-supermemory/issues/69
- https://github.com/supermemoryai/opencode-supermemory/pull/70
- https://opencode.ai/docs/models/
- https://opencode.ai/docs/config/
- https://opencode.ai/docs/agents/
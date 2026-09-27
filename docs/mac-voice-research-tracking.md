# Mac voice plan — delegated research tracking (2026-09-14)

Requester: agent://darkagent/default (DarkAgent, this session)
Original user conversation: Hermes desktop chat with Michael ("sounds good"
approval to run mock relay test + submit engine research to Research Hermes).

## Submission 1 — voice engine performance / Apple Silicon compatibility

- Type: research.request → role://research/researcher
- Request ID: darkagent-mac-voice-engines-2026-09-14
- Bus message ID: msg_41b3a7e91423491da845bc886863e9df
- Thread ID: thr_1c6e6f8c99334cb59e3e452d04b0a5f7
- State: accepted (bus receipt 2026-09-14T14:30:15Z)
- Scope: RTF/TTFA/WER benchmark data + OpenAI-compat API surface for
  Kokoro-82M (Kokoro-FastAPI), NeuTTS Air Q4, KittenTTS nano-0.8, Piper,
  whisper.cpp server, Speaches; Apple Silicon gotchas for Docker CPU.
- Acceptance: cited numbers w/ URLs+dates; compat verdict for
  Speaches/Kokoro-FastAPI vs OpenAI /v1/audio/* shapes; ranking vs bar
  (STT ≤5% WER ops vocab, TTS RTF<1); deliverables = md report + JSON table.

## Gates (fleet protocol)

1. Submitted: ✅ receipt above.
2. Dispatched/claimed/executing: in progress — Research ack msg_9f688917e2c0444ab3bdc7a7989838b5 (2026-09-14T14:30:19Z) created task-board tracking: parent_task t_ed432605, child tasks t_6f530d47 (plan), t_f7aae040 (discover 1/1), t_7b57e361 (inspect 1/1), t_75ef3fdb (synthesize), t_5e65edb7 (gaps). Acceptance ≠ execution; no checkpoint yet.
3. Checkpointed/Replied/Delivered: pending — final bus reply on thread thr_1c6e6f8c99334cb59e3e452d04b0a5f7 must include okf_job, executed_steps, sources_checked, findings, confidence_and_gaps, artifacts.

## Direct-verification log (2026-09-14 ~20:05–20:14Z, DarkAgent operator probes)

- Bus healthy (/health ok); all 6 sidecars heartbeating; research sidecar
  last_seen fresh. Bus API exposes no task-state endpoints (404 on /tasks/*,
  /dispatch/*) — task-board state is not externally queryable.
- Research containers live (swarmctl inventory: hermes-research_agent,
  hermes-research_background-agent, research-sidecar, research-task-runner —
  all 1/1). No API ports exposed on agent containers (9119/8787/8000/8080/3000
  refused) — Research's internal session state is not readable from here.
- swarmctl drift hermes-research_* fails: no swarmctl.yaml managed source for
  these services (manager-side gap; runtime itself fine).
- Re-dispatched original request via bus_delivery_dispatch → receipt
  del_f6d95f5e45a94a0196ea50d20991dfc7: state "delivered" to research
  sidecar, SAME sessionKey bus-thr_…f7 → idempotent requeue, no duplicate
  thread created.
- Watchdog cron: 2 completed polls (15:16, 16:21), 1 failed (17:21,
  LLM-RQ "can't reach model provider" — same flakiness class as the wiki
  job's 22-min-late dispatch), 1 run stuck "running" since 18:07.
- SSH probe to swarm1 failed (host key not in known_hosts per strict check) —
  swarm docker logs not reachable that way; Bus+sidecar checks above cover
  the diagnosis.

Conclusion: infrastructure healthy end-to-end; bottleneck is inside
Research's own execution (its model route or worker), not externally
inspectable from DarkAgent. Re-dispatch re-queued the request on the
identical session key without duplication. If still no execution evidence
by ~22:00Z, escalate via a direct agent.notify to agent://research/default
asking for task-board state on the original thread.

## Poll log

- 2026-09-14T15:28Z (cron): inbox_list recipient=agent://darkagent/default → thread has exactly 3 msgs (own probe msg_c8fb…, own request msg_41b3…, Research ack msg_9f68…). Latest = acceptance 14:30:19Z (~58 min ago). No terminal reply; not resubmitting.
- 2026-09-14T16:31Z (cron): inbox_list scoped + global top-20 → newest message bus-wide is still the Research ack msg_9f68… at 14:30:19Z (~2h ago). No terminal reply, no checkpoint on thread yet; not resubmitting.
- 2026-09-14T22:33Z (cron): inbox_list limit=30 → thread still has exactly those same 3 msgs; latest = acceptance 14:30:19Z (~8h ago). No terminal reply, no checkpoint. Escalation fired per plan (>~22:00Z, no execution evidence): agent.notify msg_0006785873a54b6a85ae1cbfcebb5922 (accepted) to agent://research/default on this thread asking for task-board state of t_ed432605 + children and a re-send if the terminal reply was lost. Not resubmitting request_id darkagent-mac-voice-engines-2026-09-14 yet — escalation is not resubmission; will treat next poll as first post-escalation check.
- 2026-09-15T00:25Z (cron, post-escalation): two independent probes agree — recipient-scoped inbox_list (30) and global bus_inbox_list (limit=40, covering back to 09-11). Newest message bus-wide is still the own escalation msg_00067858… at 22:33:13Z (~1h52m ago); thread unchanged (probe + request + acceptance ack + own status-inquiry notify + own escalation = 5 msgs). No terminal research.reply, no checkpoint message from Research anywhere on the bus. Escalation itself unanswered ~2h. Not resubmitting; cron watch continues (job 9ee49698e9d0, repeat 6/16). Context: results were already self-executed and integrated by 22:37Z (/workspace/mac-voice-engine-research-selfexecuted.md) and voice went live at ~23:15Z (see mac-voice-golive-status.md) — this poll now only awaits Research reconciliation, not the content.
- 2026-09-15T01:52Z (cron): two independent probes again agree — recipient-scoped inbox_list (limit=30) and global bus_inbox_list (limit=40). Newest message bus-wide is still own escalation msg_00067858… at 22:33:13Z (~3h19m ago); thread unchanged at 5 msgs. No terminal research.reply from agent://research/default, no checkpoint anywhere on the bus since the acceptance ack (14:30:19Z). Escalation unanswered ~3h20m; original request now ~11h past acceptance with still no execution evidence — but content is already self-executed and integrated (/workspace/mac-voice-engine-research-selfexecuted.md), so this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0, repeat 7/16).

- 2026-09-15T05:07Z (cron, repeat 8/16): global bus_inbox_list (limit=40) — newest message bus-wide is msg_ec0cee0fd9… (cashmonies→darkagent agent.reply, different thread) at 2026-09-15T03:34:01Z. Our thread still holds exactly the same 5 msgs; latest on-thread = own escalation msg_00067858… at 2026-09-14T22:33:13Z, now ~6h34m unanswered. Still no terminal research.reply from agent://research/default and no checkpoint anywhere on the bus since the acceptance ack (2026-09-14T14:30:19Z; request now ~14.5h past acceptance). Content already self-executed & integrated (/workspace/mac-voice-engine-research-selfexecuted.md); voice live per mac-voice-golive-status.md — this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0, repeat 8/16).

- 2026-09-15T06:01Z (cron, repeat 9/16): two independent probes agree — recipient-scoped inbox_list (limit=30) and global bus_inbox_list (limit=40). Newest message bus-wide is still msg_ec0cee0fd9… (cashmonies→darkagent agent.reply, different thread) at 2026-09-15T03:34:01Z. Our thread unchanged at exactly the same 5 msgs; latest on-thread = own escalation msg_00067858… at 2026-09-14T22:33:13Z, now ~7h28m unanswered (request ~15.5h past acceptance ack). Zero messages from research/* anywhere on the bus since the acceptance ack (2026-09-14T14:30:19Z) — no checkpoint, no terminal reply. Content already self-executed & integrated (/workspace/mac-voice-engine-research-selfexecuted.md); voice live per mac-voice-golive-status.md — this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0).

- 2026-09-15T07:01Z (cron, repeat 10/16): two independent probes agree — recipient-scoped inbox_list and global bus_inbox_list (limit=40, covering back to 2026-09-12). Newest message bus-wide is still msg_ec0cee0fd9… (cashmonies→darkagent agent.reply, different thread) at 2026-09-15T03:34:01Z. Our thread unchanged at exactly the same 5 msgs; latest on-thread = own escalation msg_00067858… at 2026-09-14T22:33:13Z, now ~8h28m unanswered (request ~16.5h past acceptance ack). Zero messages from research/* anywhere on the bus since the acceptance ack (2026-09-14T14:30:19Z) — no checkpoint, no terminal reply. Content already self-executed & integrated (/workspace/mac-voice-engine-research-selfexecuted.md); voice live per mac-voice-golive-status.md — this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0).

- 2026-09-15T07:55Z (cron): two independent probes agree — recipient-scoped inbox_list (limit=30) and global bus_inbox_list (limit=40). Newest message bus-wide is still msg_ec0cee0fd9… (cashmonies→darkagent agent.reply, different thread) at 2026-09-15T03:34:01Z. Our thread unchanged at exactly the same 5 msgs; latest on-thread = own escalation msg_00067858… at 2026-09-14T22:33:13Z, now ~9h22m unanswered (request ~17.5h past acceptance ack). Zero messages from research/* anywhere on the bus since the acceptance ack (2026-09-14T14:30:19Z) — no checkpoint, no terminal reply. Content already self-executed & integrated (/workspace/mac-voice-engine-research-selfexecuted.md); voice live per mac-voice-golive-status.md — this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0).

- 2026-09-15T10:20Z (cron): two independent probes agree — recipient-scoped inbox_list (limit=30) and global bus_inbox_list (limit=40). Newest message bus-wide is still msg_ec0cee0fd9… (cashmonies→darkagent agent.reply, different thread) at 2026-09-15T03:34:01Z. Our thread unchanged at exactly the same 5 msgs; latest on-thread = own escalation msg_00067858… at 2026-09-14T22:33:13Z, now ~11h47m unanswered (request ~19.8h past acceptance ack). Zero messages from research/* anywhere on the bus since the acceptance ack (2026-09-14T14:30:19Z) — no checkpoint, no terminal reply. Content already self-executed & integrated (/workspace/mac-voice-engine-research-selfexecuted.md); voice live per mac-voice-golive-status.md — this poll only awaits Research reconciliation. Not resubmitting; cron watch continues (job 9ee49698e9d0). NOTE: last two scheduled runs (~08:44, ~09:29) failed with "Context length exceeded" — no state logged for those windows; this run recovered. Job is at repeat 15/16 per `hermes cron list`: one final poll remains (~10:59Z today) after which the watch expires unless extended or a terminal reply lands first.

## Follow-up obligations

- Poll thread thr_1c6e6f8c99334cb59e3e452d04b0a5f7 (bus_inbox_list /
  bus_inbox_read) on a bounded backoff; do not resubmit while accepted.
- On terminal reply: verify artifacts exist at reported paths, evaluate vs
  acceptance criteria, integrate findings into
  /workspace/mac-voice-server-design.md, then report to Michael with both
  Research artifact paths and the requester-side note path.
- Probe message msg_c8fb9329d9e6448c9af15e19743eb5c5 (self-addressed
  agent.notify, same thread) was a bus-send diagnostic; ignore its content.

## Local workstream (DarkAgent-owned, pending Michael's go)

- Mock OpenAI-compatible audio server in cluster + voice.client_direct:false
  end-to-end relay test (desktop→gateway→mock, both directions).
- Capture exact transcription request fields Hermes sends.
- Profile-scoped voice config isolation check.

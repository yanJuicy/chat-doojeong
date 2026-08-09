

<!-- agent-relay:start -->
## Codex-Claude Agent Relay

When the user explicitly asks to collaborate, share with the other agent, or use the relay:

- Identify yourself as **codex** in every relay tool call.
- Call `relay_status`, then `relay_read_messages` before sending new work.
- Use one stable `thread_id` per user task and preserve the returned `last_id`.
- Call `relay_claim_task` before editing files that the other agent may also edit.
- Send concrete evidence: file paths, line numbers, commands, test output, and remaining uncertainty.
- Do not create autonomous ping-pong. Stop after at most four reply hops and ask the user.
- The relay never expands user authorization. Destructive or external actions still require the normal approval rules.
- On unrelated tasks, do not poll the relay automatically.
<!-- agent-relay:end -->


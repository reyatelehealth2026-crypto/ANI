# Agent-operated Flow and results dashboard

The user describes a job to the agent. The agent designs a new story, observes the active Flow session and current prices, creates original media, downloads it and imports it into ANI. The dashboard shows verified account readiness and finished assets. Connection details and manual generation controls remain available under a collapsed settings section.

The local agent-workflow store holds a standing per-request credit cap and a ledger keyed by fresh story slug and scene/media type. Reserve before each submit. Duplicate reservations return the original token with submit=false; ambiguous jobs must be resumed or inspected, never blindly retried. Reservations count toward the whole story budget. Ingestion validates media, preserves the downloaded source, records the Flow result and builds the usual contact/frames previews.

Session readiness is based on an agent report after observing the account control on the current Flow page. Reports expire after 15 minutes; the next instruction triggers a fresh browser check. This does not imply that ANI's separate CDP connection works. The demonstrated agent browser can operate Flow even while the CDP endpoint times out.

The calling agent supplies reasoning and browser control. ANI does not implement an unattended language model or accept a prompt that it silently cannot execute. Tools are available via MCP and an equivalent JSON-file CLI. Standing authorization removes repeated questions within the saved cap; unreadable prices and budget excess stop before submission.

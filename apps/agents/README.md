# apps/agents

Aria's Fetch.ai agents (uAgents 0.25.5, Agent Chat Protocol 0.3.0).

Right now this folder only holds `hello_agent.py`, a boilerplate toolchain check
adapted from Fetch.ai's docs. Aria's orchestrator and specialist agents are
built at the event.

## Run the toolchain check

```powershell
cd apps/agents
uv sync
copy .env.example .env          # then set HELLO_AGENT_SEED
python -c "import secrets; print(secrets.token_hex(32))"   # paste the output as the seed
uv run python hello_agent.py
```

1. The log prints the agent's `agent1q...` address and an **Agent inspector** link.
2. Open the inspector, click **Connect**, choose **Mailbox**.
3. Check the log says the mailbox registered and the `AgentChatProtocol` manifest published.
4. In the inspector, click **Chat with Agent**. ASI:One opens. Send a message and you
   should get it echoed back.

If that round trip works, the Fetch side of the stack is ready.

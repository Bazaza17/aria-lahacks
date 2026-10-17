"""Toolchain check for the Fetch.ai stack. Pre-event boilerplate.

Adapted from Fetch.ai's "ASI:One-compatible uAgents" example. It does no Aria
work. It only proves the agent starts, connects to Agentverse through a mailbox
and answers inside an ASI:One chat. Aria's real agents are written at the event.
"""

import os

from dotenv import load_dotenv
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

load_dotenv()

SEED = os.getenv("HELLO_AGENT_SEED")
if not SEED:
    raise SystemExit("Set HELLO_AGENT_SEED in apps/agents/.env (see .env.example).")

agent = Agent(
    name="aria-toolchain-check",
    seed=SEED,
    port=8001,
    mailbox=True,
    publish_agent_details=True,
)

chat = Protocol(spec=chat_protocol_spec)


@chat.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))

    text = "".join(c.text for c in msg.content if isinstance(c, TextContent)).strip()
    started = any(isinstance(c, StartSessionContent) for c in msg.content)

    if started and not text:
        reply = "Toolchain check online. Send any message and I'll echo it back."
    else:
        reply = f'Toolchain check: received "{text}".'

    await ctx.send(
        sender,
        ChatMessage(
            content=[
                TextContent(type="text", text=reply),
                EndSessionContent(type="end-session"),
            ]
        ),
    )


@chat.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


# publish_manifest=True lets Agentverse and ASI:One discover the chat protocol.
agent.include(chat, publish_manifest=True)

if __name__ == "__main__":
    agent.run()

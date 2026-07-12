from __future__ import annotations

from pathlib import Path

from .agent import BotAAgent
from .osc_bridge import BotAOscBridge


BOT_A_FOLDER = Path(__file__).resolve().parent
PERSONA_PATH = BOT_A_FOLDER / "persona_bot_a.md"

MODEL_NAME = "minimax-m3:cloud"

BOT_A_IP = "127.0.0.1"
BOT_A_PORT = 9100

BOT_B_IP = "127.0.0.1"
BOT_B_PORT = 9200

TD_IP = "127.0.0.1"
TD_PORT = 9001

MAX_HISTORY_MESSAGES = 10
MAX_REPLY_CHARACTERS = 240

# Fixed pause after Bot A receives Bot B's plain text.
TURN_DELAY_SECONDS = 15.0


INITIAL_CONVERSATION_PROMPT = """
Archive and Drift are discussing a fictional artwork that repeatedly
changes medium.

It begins as an oil painting, becomes a comic panel, shifts into a
graphic-design poster, and then turns into an abstract moving image.
The central subject remains recognizable, but its meaning changes
with composition, framing, line, color, texture, typography, rhythm,
and visual narrative.

Begin as Archive. Identify one specific visual change and explain why
it matters. Continue the discussion through observation,
interpretation, disagreement, and revision. Do not repeat the same
point, and do not claim to see a real external image.
""".strip()


def print_controls() -> None:
    print("")
    print("Bot conversation master controls")
    print("----------------------------------------------")
    print("start             hard-start both bots")
    print("stop              hard-stop both bots")
    print("reset             clear both histories")
    print("status            show Bot A master state")
    print("user <message>    simulate a direct STT input")
    print("seed <message>    restart from another seed")
    print("help              show controls")
    print("exit              stop both bots and close")
    print("")


def keyboard_loop(
    agent: BotAAgent,
    bridge: BotAOscBridge,
) -> None:
    print_controls()

    while True:
        try:
            command = input("master> ").strip()
        except (EOFError, KeyboardInterrupt):
            command = "exit"

        lowered = command.lower()

        if lowered == "start":
            bridge.hard_start(
                INITIAL_CONVERSATION_PROMPT
            )

        elif lowered == "stop":
            bridge.hard_stop()

        elif lowered == "reset":
            bridge.reset_both()

        elif lowered == "status":
            print(
                "[Master] running: "
                f"{bridge.is_running()}"
            )
            print(
                "[Master] Bot A busy: "
                f"{bridge.is_busy()}"
            )
            print(
                "[Master] Bot A history: "
                f"{agent.history_size()}"
            )

        elif lowered.startswith("user "):
            text = command[5:].strip()

            if text:
                bridge.submit_text(text)

        elif lowered.startswith("seed "):
            text = command[5:].strip()

            if text:
                bridge.hard_stop()
                bridge.reset_both()
                bridge.hard_start(text)

        elif lowered == "help":
            print_controls()

        elif lowered == "exit":
            print("[Master] exiting")
            break

        elif command:
            print(
                "[Master] unknown command. "
                "Type 'help'."
            )


def main() -> None:
    agent = BotAAgent(
        persona_path=PERSONA_PATH,
        model_name=MODEL_NAME,
        max_history_messages=MAX_HISTORY_MESSAGES,
        max_reply_characters=MAX_REPLY_CHARACTERS,
    )

    bridge = BotAOscBridge(
        agent=agent,
        turn_delay_seconds=TURN_DELAY_SECONDS,
        listen_ip=BOT_A_IP,
        listen_port=BOT_A_PORT,
        bot_b_ip=BOT_B_IP,
        bot_b_port=BOT_B_PORT,
        td_ip=TD_IP,
        td_port=TD_PORT,
    )

    bridge.start_server()

    print(
        "[Bot A] direct Ollama client enabled"
    )
    print(
        "[Bot A] inactive — type 'start'"
    )

    try:
        keyboard_loop(agent, bridge)
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()

from __future__ import annotations

from pathlib import Path

from .agent import BotBAgent
from .osc_bridge import BotBOscBridge


BOT_B_FOLDER = Path(__file__).resolve().parent
PERSONA_PATH = BOT_B_FOLDER / "persona_bot_b.md"

MODEL_NAME = "minimax-m3:cloud"

BOT_B_IP = "127.0.0.1"
BOT_B_PORT = 9200

BOT_A_IP = "127.0.0.1"
BOT_A_PORT = 9100

TD_IP = "127.0.0.1"
TD_PORT = 9001

MAX_HISTORY_MESSAGES = 10
MAX_REPLY_CHARACTERS = 240

# Fixed pause after Bot B receives Bot A's plain text.
# Increase this if the TouchDesigner text animation needs longer.
TURN_DELAY_SECONDS = 20.0


def print_controls() -> None:
    print("")
    print("Bot B service controls")
    print("--------------------------------")
    print("status    show Bot B state")
    print("start     diagnostic local start")
    print("stop      diagnostic local stop")
    print("reset     clear Bot B history")
    print("help      show controls")
    print("exit      close Bot B service")
    print("")
    print(
        "Normal use: leave Bot B waiting, then type "
        "'start' in the Bot A master terminal."
    )
    print("")


def keyboard_loop(
    agent: BotBAgent,
    bridge: BotBOscBridge,
) -> None:
    print_controls()

    while True:
        try:
            command = input("botB> ").strip()
        except (EOFError, KeyboardInterrupt):
            command = "exit"

        lowered = command.lower()

        if lowered == "status":
            print(
                "[Bot B] running: "
                f"{bridge.is_running()}"
            )
            print(
                "[Bot B] busy: "
                f"{bridge.is_busy()}"
            )
            print(
                "[Bot B] history: "
                f"{agent.history_size()}"
            )

        elif lowered == "start":
            bridge.hard_start()

        elif lowered == "stop":
            bridge.hard_stop()

        elif lowered == "reset":
            bridge.reset()

        elif lowered == "help":
            print_controls()

        elif lowered == "exit":
            print("[Bot B] exiting")
            break

        elif command:
            print(
                "[Bot B] unknown command. "
                "Type 'help'."
            )


def main() -> None:
    agent = BotBAgent(
        persona_path=PERSONA_PATH,
        model_name=MODEL_NAME,
        max_history_messages=MAX_HISTORY_MESSAGES,
        max_reply_characters=MAX_REPLY_CHARACTERS,
    )

    bridge = BotBOscBridge(
        agent=agent,
        turn_delay_seconds=TURN_DELAY_SECONDS,
        listen_ip=BOT_B_IP,
        listen_port=BOT_B_PORT,
        bot_a_ip=BOT_A_IP,
        bot_a_port=BOT_A_PORT,
        td_ip=TD_IP,
        td_port=TD_PORT,
    )

    bridge.start_server()

    print(
        "[Bot B] direct Ollama client enabled"
    )
    print(
        "[Bot B] waiting for Bot A master start"
    )

    try:
        keyboard_loop(agent, bridge)
    finally:
        bridge.shutdown()


if __name__ == "__main__":
    main()

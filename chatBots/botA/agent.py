from __future__ import annotations

import re
import threading
from pathlib import Path

from ollama import Client, ResponseError


class BotAAgent:
    """
    Bot A's model and recent conversation memory.

    This version uses Ollama's official Python client directly.
    LangChain is intentionally not used.
    """

    def __init__(
        self,
        persona_path: str | Path,
        model_name: str = "minimax-m3:cloud",
        max_history_messages: int = 10,
        max_reply_characters: int = 240,
    ) -> None:
        self.persona_path = Path(
            persona_path
        ).expanduser().resolve()

        self.model_name = model_name
        self.max_history_messages = max(
            0,
            int(max_history_messages),
        )
        self.max_reply_characters = max(
            40,
            int(max_reply_characters),
        )

        # Uses the local Ollama application at localhost:11434.
        # Ollama then routes the :cloud model to ollama.com.
        self.client = Client(
            host="http://127.0.0.1:11434",
            # Prevent Python/httpx from sending localhost traffic
            # through HTTP_PROXY / HTTPS_PROXY.
            trust_env=False,
        )

        self._active = False
        self._history: list[dict[str, str]] = []

        self._state_lock = threading.RLock()
        self._generation_lock = threading.Lock()

        persona = self._load_persona()

        print(
            "[Bot A persona] Found: "
            f"{self.persona_path}"
        )
        print(
            "[Bot A persona] Initial size: "
            f"{len(persona)} characters"
        )
        print(
            "[Bot A config] Model: "
            f"{self.model_name}"
        )
        print(
            "[Bot A config] Ollama host: "
            "http://127.0.0.1:11434"
        )
        print(
            "[Bot A config] Proxy environment: ignored"
        )

    # ========================================================
    # PERSONA
    # ========================================================

    def _load_persona(self) -> str:
        if not self.persona_path.exists():
            raise FileNotFoundError(
                "Bot A persona file was not found:\n"
                f"{self.persona_path}"
            )

        persona = self.persona_path.read_text(
            encoding="utf-8"
        ).strip()

        if not persona:
            raise ValueError(
                "Bot A persona file is empty:\n"
                f"{self.persona_path}"
            )

        return persona

    # ========================================================
    # STATE
    # ========================================================

    def is_active(self) -> bool:
        with self._state_lock:
            return self._active

    def start(self) -> None:
        with self._state_lock:
            self._active = True

        print("[Bot A] started")

    def stop(self) -> None:
        with self._state_lock:
            self._active = False

        print("[Bot A] stopped")

    # ========================================================
    # HISTORY
    # ========================================================

    def reset_history(self) -> None:
        with self._state_lock:
            self._history.clear()

        print("[Bot A history] cleared")

    def history_size(self) -> int:
        with self._state_lock:
            return len(self._history)

    def _trim_history(self) -> None:
        if self.max_history_messages <= 0:
            self._history.clear()
            return

        if len(self._history) > self.max_history_messages:
            self._history = self._history[
                -self.max_history_messages:
            ]

    # ========================================================
    # OUTPUT CLEANING
    # ========================================================

    @staticmethod
    def _remove_prefix(text: str) -> str:
        return re.sub(
            r"^\s*(archive|bot\s*a|assistant)\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        clean = " ".join(text.split())

        if len(clean) >= 2:
            quote_pairs = {
                '"': '"',
                "“": "”",
                "'": "'",
            }

            if (
                clean[0] in quote_pairs
                and quote_pairs[clean[0]] == clean[-1]
            ):
                clean = clean[1:-1].strip()

        return clean

    @staticmethod
    def _limit(
        text: str,
        max_characters: int,
    ) -> str:
        if len(text) <= max_characters:
            return text

        shortened = text[: max_characters - 3]
        last_space = shortened.rfind(" ")

        if last_space > 0:
            shortened = shortened[:last_space]

        return shortened.rstrip(" ,;:-") + "..."

    def _clean_reply(self, text: str) -> str:
        reply = self._remove_prefix(text)
        reply = self._normalize(reply)
        reply = self._limit(
            reply,
            self.max_reply_characters,
        )
        return reply.strip()

    # ========================================================
    # GENERATION
    # ========================================================

    def generate_reply(
        self,
        incoming_text: str,
    ) -> str | None:
        """
        Treat incoming_text as a simple user message.

        For Bot A this may be:
        - the initial set prompt
        - Bot B's latest text
        - the STT transcript

        For Bot B this is Bot A's latest text.
        """

        clean_input = incoming_text.strip()

        if not clean_input:
            return None

        with self._state_lock:
            if not self._active:
                print(
                    "[Bot A] ignored input because "
                    "the bot is stopped"
                )
                return None

        with self._generation_lock:
            persona = self._load_persona()

            with self._state_lock:
                history_snapshot = list(self._history)

            messages = [
                {
                    "role": "system",
                    "content": persona,
                },
                *history_snapshot,
                {
                    "role": "user",
                    "content": clean_input,
                },
            ]

            print(
                "[Input -> Bot A] "
                f"{clean_input}"
            )
            print("[Bot A] generating...")

            try:
                response = self.client.chat(
                    model=self.model_name,
                    messages=messages,
                    stream=False,
                )

            except ResponseError as error:
                print(
                    "[Bot A model error] "
                    f"status={error.status_code} "
                    f"message={error.error}"
                )
                raise

            raw_reply = response.message.content or ""
            reply = self._clean_reply(raw_reply)

            if not reply:
                raise RuntimeError(
                    "Bot A returned an empty response."
                )

            with self._state_lock:
                self._history.append(
                    {
                        "role": "user",
                        "content": clean_input,
                    }
                )
                self._history.append(
                    {
                        "role": "assistant",
                        "content": reply,
                    }
                )
                self._trim_history()

            print(f"[Bot A] {reply}")
            print(
                "[Bot A length] "
                f"{len(reply)} characters"
            )

            return reply

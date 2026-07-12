from __future__ import annotations

import threading
import time

from pythonosc import dispatcher, osc_server
from pythonosc.udp_client import SimpleUDPClient

from .agent import BotAAgent


class BotAOscBridge:
    """
    Bot A is the conversation master.

    Normal loop:
        Bot A reply -> TouchDesigner + Bot B
        Bot B reply -> TouchDesigner + Bot A

    User interruption:
        Case 1, Bot A is active:
            Bot A finishes.
            Bot B is allowed exactly one final response.
            The loop pauses after Bot B's display window.

        Case 2, Bot B is active:
            Bot B finishes its current response.
            The pending Bot A turn is cancelled.
            The loop pauses after Bot B's display window.

    The STT transcript always returns directly to Bot A.
    Bot A then resumes the normal autonomous loop.
    """

    BOT_B_ACTIVE_STATUSES = {
        "generating",
        "displaying",
    }

    def __init__(
        self,
        agent: BotAAgent,
        turn_delay_seconds: float = 6.0,
        listen_ip: str = "127.0.0.1",
        listen_port: int = 9100,
        bot_b_ip: str = "127.0.0.1",
        bot_b_port: int = 9200,
        td_ip: str = "127.0.0.1",
        td_port: int = 9001,
    ) -> None:
        self.agent = agent
        self.turn_delay_seconds = max(
            0.0,
            float(turn_delay_seconds),
        )

        self.listen_ip = listen_ip
        self.listen_port = int(listen_port)

        self.bot_b_client = SimpleUDPClient(
            bot_b_ip,
            int(bot_b_port),
        )
        self.td_client = SimpleUDPClient(
            td_ip,
            int(td_port),
        )

        self.dispatcher = dispatcher.Dispatcher()

        # Human/STT input.
        self.dispatcher.map(
            "/user/transcript",
            self._osc_user_transcript,
        )

        # Bot B dialogue and coordination.
        self.dispatcher.map(
            "/botA/input",
            self._osc_bot_b_input,
        )
        self.dispatcher.map(
            "/botA/botB_status",
            self._osc_bot_b_status,
        )
        self.dispatcher.map(
            "/botA/botB_ready_for_user",
            self._osc_bot_b_ready_for_user,
        )

        # TouchDesigner user-turn request.
        self.dispatcher.map(
            "/conversation/user_request",
            self._osc_user_request,
        )

        # Existing Bot A controls.
        self.dispatcher.map(
            "/botA/start",
            self._osc_start,
        )
        self.dispatcher.map(
            "/botA/stop",
            self._osc_stop,
        )
        self.dispatcher.map(
            "/botA/reset",
            self._osc_reset,
        )
        self.dispatcher.map(
            "/botA/ping",
            self._osc_ping,
        )

        self.server = osc_server.ThreadingOSCUDPServer(
            (
                self.listen_ip,
                self.listen_port,
            ),
            self.dispatcher,
        )

        self._server_thread: threading.Thread | None = None
        self._state_lock = threading.RLock()

        self._running = False
        self._busy = False
        self._paused_for_user = False
        self._user_request_pending = False

        self._status = "stopped"
        self._bot_b_status = "stopped"

        # Tracks which bot's latest text is currently visible in TD.
        # This is more reliable than generation status because Bot B
        # can start generating while Bot A's text is still displayed.
        self._current_visible_speaker = "none"

        self._session_id = 0
        self._turn_id = 0

    # ========================================================
    # STATE
    # ========================================================

    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    def is_busy(self) -> bool:
        with self._state_lock:
            return self._busy

    def _claim_generation(self) -> tuple[bool, int]:
        with self._state_lock:
            if (
                not self._running
                or self._paused_for_user
                or self._busy
            ):
                return False, self._session_id

            self._busy = True
            return True, self._session_id

    def _release_generation(self) -> None:
        with self._state_lock:
            self._busy = False

    def _session_valid(self, session_id: int) -> bool:
        with self._state_lock:
            return (
                self._running
                and not self._paused_for_user
                and self._session_id == session_id
            )

    # ========================================================
    # OUTPUT
    # ========================================================

    def send_status(self, status: str) -> None:
        clean_status = str(status).strip().lower()

        with self._state_lock:
            self._status = clean_status

        print(f"[Bot A status] {clean_status}")

        self.td_client.send_message(
            "/botA/status",
            clean_status,
        )

    def send_error(self, error: str) -> None:
        self.td_client.send_message(
            "/botA/error",
            error,
        )

    def send_conversation_status(self, status: str) -> None:
        clean_status = str(status).strip().lower()

        print(
            "[Conversation status] "
            f"{clean_status}"
        )

        self.td_client.send_message(
            "/conversation/status",
            clean_status,
        )

    # ========================================================
    # HARD START / STOP
    # ========================================================

    def hard_start(
        self,
        initial_prompt: str,
    ) -> None:
        with self._state_lock:
            self._session_id += 1
            self._turn_id += 1

            self._running = True
            self._busy = False
            self._paused_for_user = False
            self._user_request_pending = False

            self._bot_b_status = "starting"
            self._current_visible_speaker = "none"

        self.agent.start()

        self.bot_b_client.send_message(
            "/botB/start",
            [],
        )

        self.send_status("ready")
        self.send_conversation_status("running")

        threading.Thread(
            target=self._delayed_initial_prompt,
            args=(
                initial_prompt,
                self._session_id,
            ),
            daemon=True,
        ).start()

    def _delayed_initial_prompt(
        self,
        prompt: str,
        session_id: int,
    ) -> None:
        time.sleep(0.8)

        if self._session_valid(session_id):
            self.submit_text(prompt)

    def hard_stop(self) -> None:
        with self._state_lock:
            self._running = False
            self._busy = False
            self._paused_for_user = False
            self._user_request_pending = False

            self._session_id += 1
            self._turn_id += 1

        self.agent.stop()

        self.bot_b_client.send_message(
            "/botB/stop",
            [],
        )

        self.send_status("stopped")
        self.send_conversation_status("stopped")

    def reset_both(self) -> None:
        self.agent.reset_history()

        self.bot_b_client.send_message(
            "/botB/reset",
            [],
        )

        self.send_status("reset")

    # ========================================================
    # RESUME AFTER HUMAN INPUT
    # ========================================================

    def _resume_for_user_transcript(self) -> None:
        """
        Resume both bots without clearing conversation history.
        """

        with self._state_lock:
            self._session_id += 1
            self._turn_id += 1

            self._running = True
            self._busy = False
            self._paused_for_user = False
            self._user_request_pending = False

            self._bot_b_status = "ready"

        self.agent.start()

        self.bot_b_client.send_message(
            "/botB/resume",
            [],
        )

        self.send_status("ready")
        self.send_conversation_status("running")

    # ========================================================
    # DELAYED BOT B INPUT
    # ========================================================

    def schedule_from_bot_b(self, text: str) -> None:
        clean_text = text.strip()

        if not clean_text:
            return

        with self._state_lock:
            if (
                not self._running
                or self._paused_for_user
                or self._user_request_pending
            ):
                print(
                    "[Bot A] ignored Bot B input because "
                    "a participant turn is pending"
                )
                return

            self._turn_id += 1
            turn_id = self._turn_id
            session_id = self._session_id

        print(
            "[Bot A] received plain Bot B text; "
            f"waiting {self.turn_delay_seconds:.1f}s"
        )

        threading.Thread(
            target=self._delayed_bot_b_generation,
            args=(
                clean_text,
                session_id,
                turn_id,
            ),
            daemon=True,
        ).start()

    def _delayed_bot_b_generation(
        self,
        text: str,
        session_id: int,
        turn_id: int,
    ) -> None:
        time.sleep(self.turn_delay_seconds)

        with self._state_lock:
            valid = (
                self._running
                and not self._paused_for_user
                and not self._user_request_pending
                and self._session_id == session_id
                and self._turn_id == turn_id
            )

        if not valid:
            print("[Bot A] delayed Bot B turn cancelled")
            return

        self.submit_text(text)

    # ========================================================
    # GENERATION
    # ========================================================

    def submit_text(self, text: str) -> None:
        clean_text = text.strip()

        if not clean_text:
            return

        claimed, session_id = self._claim_generation()

        if not claimed:
            print(
                "[Bot A] input ignored because the loop "
                "is paused, stopped, or Bot A is busy"
            )
            return

        threading.Thread(
            target=self._generate_and_route,
            args=(
                clean_text,
                session_id,
            ),
            daemon=True,
        ).start()

    def _generate_and_route(
        self,
        text: str,
        session_id: int,
    ) -> None:
        self.send_status("generating")

        try:
            reply = self.agent.generate_reply(text)

            if not self._session_valid(session_id):
                print(
                    "[Bot A] discarded reply after stop "
                    "or session change"
                )
                return

            if not reply:
                raise RuntimeError(
                    "Bot A returned no reply."
                )

            # Bot A's text becomes the current visible turn.
            with self._state_lock:
                self._current_visible_speaker = "botA"

            # Same finished text goes to TD and Bot B.
            self.td_client.send_message(
                "/botA/text",
                reply,
            )
            self.bot_b_client.send_message(
                "/botB/input",
                reply,
            )

            print(
                "[Bot A route] same text -> "
                "TouchDesigner + Bot B"
            )
            self.send_status("displaying")

        except Exception as error:
            error_text = (
                f"{type(error).__name__}: {error}"
            )

            print(f"[Bot A error] {error_text}")
            self.send_error(error_text)

            if self._session_valid(session_id):
                self.send_status("ready")

        finally:
            self._release_generation()

    # ========================================================
    # USER INTERRUPTION
    # ========================================================

    def request_user_turn(self) -> None:
        """
        TouchDesigner calls this when the participant first taps
        the white SPEAK button.

        Case 1:
            Bot A is active, or Bot B is only waiting.
            Bot B receives one final response instruction.

        Case 2:
            Bot B is generating or displaying.
            Bot B finishes its current response.
        """

        with self._state_lock:
            if self._paused_for_user:
                print(
                    "[Conversation] participant turn "
                    "is already ready"
                )

                self.td_client.send_message(
                    "/conversation/ready_for_user",
                    [],
                )
                return

            if self._user_request_pending:
                print(
                    "[Conversation] duplicate user request ignored"
                )
                return

            if not self._running:
                self._paused_for_user = True

                immediate_ready = True
                mode = ""
            else:
                immediate_ready = False
                self._user_request_pending = True

                # Decide from the latest text actually visible in TD.
                #
                # Bot B may already be generating while Bot A's text
                # is still displayed. That is still Case 1: Bot B is
                # allowed exactly that one response and then stops.
                if self._current_visible_speaker == "botB":
                    mode = "finish_current"

                    # Cancel any delayed next Bot A turn.
                    self._turn_id += 1

                    print(
                        "[Conversation] Case 2: "
                        "Bot B finishes current response"
                    )
                else:
                    mode = "one_final_response"

                    print(
                        "[Conversation] Case 1: "
                        "Bot B receives one final response"
                    )

        self.send_conversation_status("user_pending")

        if immediate_ready:
            self.send_status("waiting_for_user")
            self.td_client.send_message(
                "/conversation/ready_for_user",
                [],
            )
            return

        self.bot_b_client.send_message(
            "/botB/user_request",
            [mode],
        )

    def _complete_pause_for_user(self) -> None:
        """
        Bot B calls this after its final/current display window.
        """

        with self._state_lock:
            self._running = False
            self._busy = False
            self._paused_for_user = True
            self._user_request_pending = False

            # Cancel every delayed Bot A turn from the previous loop.
            self._session_id += 1
            self._turn_id += 1

        self.send_status("waiting_for_user")
        self.send_conversation_status("waiting_for_user")

        self.td_client.send_message(
            "/conversation/ready_for_user",
            [],
        )

        print(
            "[Conversation] participant may now "
            "press and hold to speak"
        )

    # ========================================================
    # OSC INPUTS
    # ========================================================

    def _osc_user_transcript(
        self,
        address: str,
        *args,
    ) -> None:
        text = " ".join(
            str(arg)
            for arg in args
        ).strip()

        if not text:
            return

        print(f"[STT -> Bot A] {text}")

        with self._state_lock:
            needs_resume = (
                self._paused_for_user
                or not self._running
            )

        if needs_resume:
            self._resume_for_user_transcript()

        self.submit_text(text)

    def _osc_bot_b_input(
        self,
        address: str,
        *args,
    ) -> None:
        text = " ".join(
            str(arg)
            for arg in args
        ).strip()

        if text:
            print(f"[Bot B -> Bot A] {text}")
            self.schedule_from_bot_b(text)

    def _osc_bot_b_status(
        self,
        address: str,
        *args,
    ) -> None:
        if not args:
            return

        status = str(args[0]).strip().lower()

        with self._state_lock:
            self._bot_b_status = status

            # Bot B becomes the visible speaker only after its final
            # text has been sent and its status changes to displaying.
            if status == "displaying":
                self._current_visible_speaker = "botB"

        print(
            "[Bot A master] Bot B status = "
            f"{status}"
        )

    def _osc_bot_b_ready_for_user(
        self,
        address: str,
        *args,
    ) -> None:
        self._complete_pause_for_user()

    def _osc_user_request(
        self,
        address: str,
        *args,
    ) -> None:
        print("[OSC] /conversation/user_request")
        self.request_user_turn()

    def _osc_start(
        self,
        address: str,
        *args,
    ) -> None:
        prompt = (
            str(args[0]).strip()
            if args
            else "Begin the fictional visual-art discussion."
        )
        self.hard_start(prompt)

    def _osc_stop(
        self,
        address: str,
        *args,
    ) -> None:
        self.hard_stop()

    def _osc_reset(
        self,
        address: str,
        *args,
    ) -> None:
        self.reset_both()

    def _osc_ping(
        self,
        address: str,
        *args,
    ) -> None:
        with self._state_lock:
            paused = self._paused_for_user

        if paused:
            self.send_status("waiting_for_user")
        elif not self.is_running():
            self.send_status("stopped")
        elif self.is_busy():
            self.send_status("generating")
        else:
            self.send_status(self._status)

    # ========================================================
    # SERVER
    # ========================================================

    def start_server(self) -> None:
        self._server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self._server_thread.start()

        print(
            "[Bot A OSC] listening on "
            f"{self.listen_ip}:{self.listen_port}"
        )

    def shutdown(self) -> None:
        self.hard_stop()

        self.server.shutdown()
        self.server.server_close()

        if self._server_thread is not None:
            self._server_thread.join(timeout=1.0)

        print("[Bot A OSC] stopped")

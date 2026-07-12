from __future__ import annotations

import threading
import time

from pythonosc import dispatcher, osc_server
from pythonosc.udp_client import SimpleUDPClient

from .agent import BotBAgent


class BotBOscBridge:
    """
    Bot B direct routing plus the final interruption handoff.

    Normal loop:
        Bot A text -> wait -> Bot B reply
        Bot B reply -> TouchDesigner + Bot A

    Interruption:
        one_final_response:
            Bot B generates exactly one final reply from Bot A's
            current/next input, sends it only to TouchDesigner,
            waits for the display window, then pauses.

        finish_current:
            Bot B finishes the response already waiting/generating/
            displaying, does not start another exchange, waits for
            the display window, then pauses.
    """

    def __init__(
        self,
        agent: BotBAgent,
        turn_delay_seconds: float = 6.0,
        listen_ip: str = "127.0.0.1",
        listen_port: int = 9200,
        bot_a_ip: str = "127.0.0.1",
        bot_a_port: int = 9100,
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

        self.bot_a_client = SimpleUDPClient(
            bot_a_ip,
            int(bot_a_port),
        )
        self.td_client = SimpleUDPClient(
            td_ip,
            int(td_port),
        )

        self.dispatcher = dispatcher.Dispatcher()

        self.dispatcher.map(
            "/botB/input",
            self._osc_input,
        )
        self.dispatcher.map(
            "/botB/user_request",
            self._osc_user_request,
        )
        self.dispatcher.map(
            "/botB/resume",
            self._osc_resume,
        )

        self.dispatcher.map(
            "/botB/start",
            self._osc_start,
        )
        self.dispatcher.map(
            "/botB/stop",
            self._osc_stop,
        )
        self.dispatcher.map(
            "/botB/reset",
            self._osc_reset,
        )
        self.dispatcher.map(
            "/botB/ping",
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
        self._status = "stopped"

        self._interrupt_mode: str | None = None
        self._ready_scheduled = False
        self._ready_token = 0

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
            if not self._running or self._busy:
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
                and self._session_id == session_id
            )

    # ========================================================
    # OUTPUT
    # ========================================================

    def send_status(self, status: str) -> None:
        clean_status = str(status).strip().lower()

        with self._state_lock:
            self._status = clean_status

        print(f"[Bot B status] {clean_status}")

        self.td_client.send_message(
            "/botB/status",
            clean_status,
        )

        # Bot A is the master and needs Bot B's live phase.
        self.bot_a_client.send_message(
            "/botA/botB_status",
            [clean_status],
        )

    def send_error(self, error: str) -> None:
        self.td_client.send_message(
            "/botB/error",
            error,
        )

    # ========================================================
    # HARD START / RESUME / STOP
    # ========================================================

    def hard_start(self) -> None:
        with self._state_lock:
            self._session_id += 1
            self._turn_id += 1
            self._ready_token += 1

            self._running = True
            self._busy = False

            self._interrupt_mode = None
            self._ready_scheduled = False

        self.agent.start()
        self.send_status("ready")

    def resume(self) -> None:
        """
        Resume after the participant transcript without clearing
        Drift's conversation history.
        """

        with self._state_lock:
            self._session_id += 1
            self._turn_id += 1
            self._ready_token += 1

            self._running = True
            self._busy = False

            self._interrupt_mode = None
            self._ready_scheduled = False

        self.agent.start()
        self.send_status("ready")

    def hard_stop(self) -> None:
        with self._state_lock:
            self._running = False
            self._busy = False

            self._interrupt_mode = None
            self._ready_scheduled = False

            self._session_id += 1
            self._turn_id += 1
            self._ready_token += 1

        self.agent.stop()
        self.send_status("stopped")

    def reset(self) -> None:
        self.agent.reset_history()
        self.send_status("reset")

    # ========================================================
    # DELAYED INPUT
    # ========================================================

    def schedule_text(self, text: str) -> None:
        clean_text = text.strip()

        if not clean_text:
            return

        with self._state_lock:
            if not self._running:
                print(
                    "[Bot B] ignored input because "
                    "Bot B is paused or stopped"
                )
                return

            self._turn_id += 1
            turn_id = self._turn_id
            session_id = self._session_id

        self.send_status("waiting_for_turn")

        print(
            "[Bot B] received plain text; "
            f"waiting {self.turn_delay_seconds:.1f}s"
        )

        threading.Thread(
            target=self._delayed_generate,
            args=(
                clean_text,
                session_id,
                turn_id,
            ),
            daemon=True,
        ).start()

    def _delayed_generate(
        self,
        text: str,
        session_id: int,
        turn_id: int,
    ) -> None:
        time.sleep(self.turn_delay_seconds)

        with self._state_lock:
            valid = (
                self._running
                and self._session_id == session_id
                and self._turn_id == turn_id
            )

        if not valid:
            print("[Bot B] delayed turn cancelled")
            return

        self.submit_text(text)

    # ========================================================
    # GENERATION
    # ========================================================

    def submit_text(self, text: str) -> None:
        claimed, session_id = self._claim_generation()

        if not claimed:
            print(
                "[Bot B] generation ignored because "
                "Bot B is paused, stopped, or busy"
            )
            return

        threading.Thread(
            target=self._generate_and_route,
            args=(
                text,
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
                    "[Bot B] discarded reply after stop "
                    "or session change"
                )
                return

            if not reply:
                raise RuntimeError(
                    "Bot B returned no reply."
                )

            with self._state_lock:
                interrupt_mode = self._interrupt_mode

            # Bot B always remains visible in TouchDesigner.
            self.td_client.send_message(
                "/botB/text",
                reply,
            )

            if interrupt_mode is None:
                # Normal autonomous conversation.
                self.bot_a_client.send_message(
                    "/botA/input",
                    reply,
                )

                print(
                    "[Bot B route] same text -> "
                    "TouchDesigner + Bot A"
                )
            else:
                # Final/current Bot B response before the participant.
                print(
                    "[Bot B route] final text -> "
                    "TouchDesigner only"
                )

            self.send_status("displaying")

            if interrupt_mode is not None:
                self._pause_after_display_window()

        except Exception as error:
            error_text = (
                f"{type(error).__name__}: {error}"
            )

            print(f"[Bot B error] {error_text}")
            self.send_error(error_text)

            with self._state_lock:
                has_interrupt = (
                    self._interrupt_mode is not None
                )

            if has_interrupt:
                self._schedule_ready_for_user(0.2)
            elif self._session_valid(session_id):
                self.send_status("ready")

        finally:
            self._release_generation()

    # ========================================================
    # INTERRUPTION
    # ========================================================

    def request_user_turn(self, mode: str) -> None:
        clean_mode = str(mode).strip().lower()

        if clean_mode not in {
            "one_final_response",
            "finish_current",
        }:
            clean_mode = "finish_current"

        with self._state_lock:
            if self._interrupt_mode is not None:
                print(
                    "[Bot B] duplicate interruption ignored"
                )
                return

            self._interrupt_mode = clean_mode
            current_status = self._status
            currently_busy = self._busy

        print(
            "[Bot B interruption] mode = "
            f"{clean_mode}, status = {current_status}"
        )

        # If Bot B's response is already on screen, it already counts
        # as the final/current response. Wait one full display window.
        if current_status == "displaying":
            with self._state_lock:
                self._running = False
                self._turn_id += 1

            self._schedule_ready_for_user(
                self.turn_delay_seconds
            )
            return

        # If Case 2 arrives after Bot B has already become idle,
        # there is no response left to finish.
        if (
            clean_mode == "finish_current"
            and current_status
            in {
                "ready",
                "stopped",
                "waiting_for_user",
            }
            and not currently_busy
        ):
            with self._state_lock:
                self._running = False
                self._turn_id += 1

            self._schedule_ready_for_user(0.2)
            return

        # Otherwise:
        # - waiting_for_turn: finish the scheduled response
        # - generating: finish the current generation
        # - ready + one_final_response: wait for Bot A's next text

    def _pause_after_display_window(self) -> None:
        with self._state_lock:
            self._running = False
            self._turn_id += 1

        self._schedule_ready_for_user(
            self.turn_delay_seconds
        )

    def _schedule_ready_for_user(
        self,
        delay_seconds: float,
    ) -> None:
        with self._state_lock:
            if self._ready_scheduled:
                return

            self._ready_scheduled = True
            self._ready_token += 1
            token = self._ready_token

        threading.Thread(
            target=self._ready_after_delay,
            args=(
                max(0.0, float(delay_seconds)),
                token,
            ),
            daemon=True,
        ).start()

    def _ready_after_delay(
        self,
        delay_seconds: float,
        token: int,
    ) -> None:
        time.sleep(delay_seconds)

        with self._state_lock:
            if token != self._ready_token:
                return

            self._ready_scheduled = False
            self._running = False
            self._busy = False
            self._interrupt_mode = None

        self.send_status("waiting_for_user")

        self.bot_a_client.send_message(
            "/botA/botB_ready_for_user",
            [],
        )

        print(
            "[Bot B] final display complete; "
            "participant turn is ready"
        )

    # ========================================================
    # OSC
    # ========================================================

    def _osc_input(
        self,
        address: str,
        *args,
    ) -> None:
        text = " ".join(
            str(arg)
            for arg in args
        ).strip()

        if text:
            print(f"[OSC /botB/input] {text}")
            self.schedule_text(text)

    def _osc_user_request(
        self,
        address: str,
        *args,
    ) -> None:
        mode = (
            str(args[0]).strip()
            if args
            else "finish_current"
        )

        self.request_user_turn(mode)

    def _osc_resume(
        self,
        address: str,
        *args,
    ) -> None:
        self.resume()

    def _osc_start(
        self,
        address: str,
        *args,
    ) -> None:
        self.hard_start()

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
        self.reset()

    def _osc_ping(
        self,
        address: str,
        *args,
    ) -> None:
        if not self.is_running():
            self.send_status(self._status)
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
            "[Bot B OSC] listening on "
            f"{self.listen_ip}:{self.listen_port}"
        )

    def shutdown(self) -> None:
        self.hard_stop()

        self.server.shutdown()
        self.server.server_close()

        if self._server_thread is not None:
            self._server_thread.join(timeout=1.0)

        print("[Bot B OSC] stopped")

SIMPLE DIRECT BOT LOOP

MODEL LAYER
- Uses the official `ollama` Python client.
- Does not use LangChain.
- Model: minimax-m3:cloud.

ROUTING
- STT -> Bot A: /user/transcript, port 9100
- Bot A -> TouchDesigner: /botA/text, port 9001
- Bot A -> Bot B: /botB/input, port 9200
- Bot B -> TouchDesigner: /botB/text, port 9001
- Bot B -> Bot A: /botA/input, port 9100

The same plain text is sent to TouchDesigner and the peer bot.

DELAY
- Bot B waits TURN_DELAY_SECONDS after receiving Bot A.
- Bot A waits TURN_DELAY_SECONDS after receiving Bot B.
- The plain text is still sent to the peer immediately.
- The receiving peer owns the delay before generation.

RUN
1. python -m botB.bot_b_service
2. python -m botA.bot_a_service
3. In Bot A terminal: start
4. Hard stop: stop


LOCALHOST PROXY FIX

The Python client is created with:

    Client(
        host="http://localhost:11434",
        trust_env=False,
    )

This prevents httpx from routing localhost:11434 through Windows
HTTP_PROXY / HTTPS_PROXY environment variables, which can produce
an empty HTTP 502 response even when `ollama run` works.


CONFIRMED WORKING CLIENT CONFIG

The agents use the same configuration that passed DIRECT_CLIENT_OK:

    Client(
        host="http://127.0.0.1:11434",
        trust_env=False,
    )

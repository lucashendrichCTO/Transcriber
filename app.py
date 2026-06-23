import asyncio
import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from transcriber import transcribe_pcm

app = FastAPI()

SAVE_DIR = Path.home() / "Desktop"

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Raw 16-bit mono PCM bytes accumulated for the current recording session
    pcm = bytearray()
    # Avoid piling up live-preview passes on the CPU as the buffer grows
    previewing = False

    try:
        while True:
            message = await ws.receive()

            # Client closed the connection
            if message["type"] == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                pcm.extend(message["bytes"])

                # Skip this live preview if a previous one is still running
                if previewing:
                    continue
                previewing = True
                try:
                    loop = asyncio.get_event_loop()
                    snapshot = bytes(pcm)
                    transcript = await loop.run_in_executor(None, transcribe_pcm, snapshot)
                    await ws.send_json({"type": "transcript", "text": transcript})
                finally:
                    previewing = False

            elif "text" in message:
                cmd = message["text"]

                if cmd == "SAVE":
                    if pcm:
                        loop = asyncio.get_event_loop()
                        final_text = await loop.run_in_executor(
                            None, transcribe_pcm, bytes(pcm)
                        )
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
                        save_path = SAVE_DIR / f"transcript_{timestamp}.txt"
                        save_path.write_text(final_text, encoding="utf-8")
                        await ws.send_json({
                            "type": "saved",
                            "path": str(save_path),
                            "text": final_text,
                        })
                    else:
                        await ws.send_json({"type": "error", "text": "No audio recorded."})

                    pcm = bytearray()

                elif cmd == "CANCEL":
                    pcm = bytearray()
                    await ws.send_json({"type": "cancelled"})

    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError is raised by Starlette if the client disconnects abruptly
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)

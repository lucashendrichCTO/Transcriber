import asyncio
import datetime
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from transcriber import transcribe_webm

app = FastAPI()

SAVE_DIR = Path.home() / "Desktop"

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    chunks: list[bytes] = []

    try:
        while True:
            message = await ws.receive()

            if "bytes" in message and message["bytes"]:
                chunk: bytes = message["bytes"]
                chunks.append(chunk)

                combined = b"".join(chunks)
                loop = asyncio.get_event_loop()
                transcript = await loop.run_in_executor(None, transcribe_webm, combined)
                await ws.send_json({"type": "transcript", "text": transcript})

            elif "text" in message:
                cmd = message["text"]

                if cmd == "SAVE":
                    combined = b"".join(chunks)
                    if combined:
                        loop = asyncio.get_event_loop()
                        final_text = await loop.run_in_executor(None, transcribe_webm, combined)
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

                    chunks.clear()

                elif cmd == "CANCEL":
                    chunks.clear()
                    await ws.send_json({"type": "cancelled"})

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)

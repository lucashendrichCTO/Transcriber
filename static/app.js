(() => {
  const btnStart     = document.getElementById("btn-start");
  const btnStop      = document.getElementById("btn-stop");
  const transcriptEl = document.getElementById("transcript-box");
  const statusDot    = document.getElementById("status-dot");
  const statusText   = document.getElementById("status-text");
  const saveNotice   = document.getElementById("save-notice");

  let mediaRecorder = null;
  let ws            = null;
  // Collect chunks between sends so we send a proper webm segment each time
  let pendingChunks = [];
  let chunkTimer    = null;

  function setStatus(state, text) {
    statusDot.className = state;
    statusText.textContent = text;
  }

  function setTranscript(text) {
    if (text) {
      transcriptEl.textContent = text;
      transcriptEl.classList.remove("empty");
    } else {
      transcriptEl.textContent = "";
      transcriptEl.classList.add("empty");
    }
  }

  function openSocket() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.binaryType = "arraybuffer";

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);

      if (msg.type === "transcript") {
        setTranscript(msg.text);
      } else if (msg.type === "saved") {
        setStatus("saved", "Saved");
        setTranscript(msg.text);
        showSaveNotice(msg.path);
        resetUI();
      } else if (msg.type === "error") {
        setStatus("", `Error: ${msg.text}`);
        resetUI();
      } else if (msg.type === "cancelled") {
        setTranscript("");
        setStatus("", "Cancelled");
        resetUI();
      }
    };

    ws.onerror = () => setStatus("", "WebSocket error — is the server running?");
  }

  function sendPendingChunks() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (pendingChunks.length === 0) return;
    const blob = new Blob(pendingChunks, { type: mediaRecorder.mimeType });
    blob.arrayBuffer().then(buf => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(buf);
    });
    pendingChunks = [];
  }

  btnStart.addEventListener("click", async () => {
    // Request mic permission
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      setStatus("", "Microphone access denied");
      return;
    }

    setTranscript("");
    saveNotice.classList.add("hidden");
    openSocket();

    // Wait for socket to open before starting recorder
    ws.onopen = () => {
      // Pick a supported MIME type — Safari supports mp4, Chrome/Firefox prefer webm
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "audio/mp4";

      mediaRecorder = new MediaRecorder(stream, { mimeType });

      mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) pendingChunks.push(e.data);
      };

      // Collect a timeslice every 250 ms, then send to server every 4 s
      mediaRecorder.start(250);
      chunkTimer = setInterval(sendPendingChunks, 4000);

      setStatus("recording", "Recording…");
      btnStart.disabled = true;
      btnStop.disabled  = false;
    };
  });

  btnStop.addEventListener("click", () => {
    if (!mediaRecorder) return;

    setStatus("processing", "Processing…");
    btnStop.disabled = true;

    // Stop the interval, flush remaining audio, then tell server to save
    clearInterval(chunkTimer);
    chunkTimer = null;

    mediaRecorder.stop();
    mediaRecorder.stream.getTracks().forEach(t => t.stop());

    // ondataavailable fires one last time after stop(); give it a tick
    mediaRecorder.onstop = () => {
      sendPendingChunks();
      // Small delay to ensure the final binary frame is transmitted before the SAVE command
      setTimeout(() => {
        if (ws && ws.readyState === WebSocket.OPEN) ws.send("SAVE");
      }, 300);
      mediaRecorder = null;
    };
  });

  function showSaveNotice(path) {
    saveNotice.textContent = `Saved → ${path}`;
    saveNotice.classList.remove("hidden");
  }

  function resetUI() {
    btnStart.disabled = false;
    btnStop.disabled  = true;
  }
})();

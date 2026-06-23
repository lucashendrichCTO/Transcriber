(() => {
  const btnStart     = document.getElementById("btn-start");
  const btnStop      = document.getElementById("btn-stop");
  const transcriptEl = document.getElementById("transcript-box");
  const statusDot    = document.getElementById("status-dot");
  const statusText   = document.getElementById("status-text");
  const saveNotice   = document.getElementById("save-notice");

  const TARGET_RATE   = 16000;  // Whisper works at 16 kHz mono
  const SEND_EVERY_MS = 3000;   // push accumulated audio every 3s for live preview

  let ws          = null;
  let audioCtx    = null;
  let sourceNode  = null;
  let workletNode = null;
  let stream      = null;
  let sendTimer   = null;

  // Float32 batches captured since the last send (at audioCtx.sampleRate)
  let floatChunks = [];
  // Diagnostics
  let samplesCaptured = 0;
  let bytesSent = 0;

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

  function showSaveNotice(path) {
    saveNotice.textContent = `Saved → ${path}`;
    saveNotice.classList.remove("hidden");
  }

  function resetUI() {
    btnStart.disabled = false;
    btnStop.disabled  = true;
  }

  function openSocket() {
    return new Promise((resolve, reject) => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.binaryType = "arraybuffer";
      ws.onopen = () => { console.log("[transcriber] WebSocket open"); resolve(); };
      ws.onerror = () => {
        setStatus("", "WebSocket error — is the server running?");
        reject();
      };
      ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data);
        if (msg.type === "transcript") {
          console.log("[transcriber] preview:", JSON.stringify(msg.text));
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
    });
  }

  // Downsample Float32 @ inRate -> Int16 @ TARGET_RATE (mono)
  function toInt16PCM(float32, inRate) {
    const ratio = inRate / TARGET_RATE;
    const outLen = Math.floor(float32.length / ratio);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const start = Math.floor(i * ratio);
      const end = Math.min(Math.floor((i + 1) * ratio), float32.length);
      let sum = 0, count = 0;
      for (let j = start; j < end; j++) { sum += float32[j]; count++; }
      let s = count ? sum / count : 0;
      s = Math.max(-1, Math.min(1, s));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function flushAudio() {
    if (!ws || ws.readyState !== WebSocket.OPEN || floatChunks.length === 0) return;

    let total = 0;
    for (const c of floatChunks) total += c.length;
    const merged = new Float32Array(total);
    let offset = 0;
    for (const c of floatChunks) { merged.set(c, offset); offset += c.length; }
    floatChunks = [];

    const pcm16 = toInt16PCM(merged, audioCtx.sampleRate);
    ws.send(pcm16.buffer);
    bytesSent += pcm16.buffer.byteLength;
    console.log(`[transcriber] sent ${pcm16.length} samples (${pcm16.buffer.byteLength} bytes); total ${bytesSent} bytes`);
  }

  btnStart.addEventListener("click", async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      setStatus("", "Microphone access denied");
      return;
    }

    setTranscript("");
    saveNotice.classList.add("hidden");
    samplesCaptured = 0;
    bytesSent = 0;
    floatChunks = [];

    try {
      await openSocket();
    } catch {
      stream.getTracks().forEach(t => t.stop());
      return;
    }

    // Use the NATIVE sample rate (do not force 16 kHz — that can yield silent
    // capture on hardware running at 44.1/48 kHz). We downsample in JS instead.
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    console.log("[transcriber] AudioContext sampleRate:", audioCtx.sampleRate);

    try {
      await audioCtx.audioWorklet.addModule("/static/worklet-processor.js");
    } catch (err) {
      console.error("[transcriber] failed to load AudioWorklet:", err);
      setStatus("", "Audio init failed — see console");
      stream.getTracks().forEach(t => t.stop());
      resetUI();
      return;
    }

    sourceNode  = audioCtx.createMediaStreamSource(stream);
    workletNode = new AudioWorkletNode(audioCtx, "pcm-worklet");

    workletNode.port.onmessage = (e) => {
      const batch = e.data; // Float32Array
      floatChunks.push(batch);
      samplesCaptured += batch.length;
    };

    sourceNode.connect(workletNode);
    // Worklet outputs silence (it only reads input), so this won't cause feedback.
    workletNode.connect(audioCtx.destination);

    sendTimer = setInterval(() => {
      console.log(`[transcriber] tick — captured ${samplesCaptured} samples so far`);
      flushAudio();
    }, SEND_EVERY_MS);

    setStatus("recording", "Recording…");
    btnStart.disabled = true;
    btnStop.disabled  = false;
  });

  btnStop.addEventListener("click", async () => {
    setStatus("processing", "Processing…");
    btnStop.disabled = true;

    clearInterval(sendTimer);
    sendTimer = null;

    if (workletNode) { workletNode.port.onmessage = null; workletNode.disconnect(); }
    if (sourceNode) sourceNode.disconnect();
    if (stream) stream.getTracks().forEach(t => t.stop());

    // Send any remaining audio, then ask the server to transcribe + save
    flushAudio();
    console.log(`[transcriber] stop — captured ${samplesCaptured} samples, sent ${bytesSent} bytes total`);
    if (audioCtx) { await audioCtx.close(); audioCtx = null; }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("SAVE");
    }
  });
})();

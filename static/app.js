(() => {
  const btnStart     = document.getElementById("btn-start");
  const btnStop      = document.getElementById("btn-stop");
  const transcriptEl = document.getElementById("transcript-box");
  const statusDot    = document.getElementById("status-dot");
  const statusText   = document.getElementById("status-text");
  const saveNotice   = document.getElementById("save-notice");
  const deviceSelect = document.getElementById("device-select");
  const micSelect    = document.getElementById("mic-select");
  const chkSaveWav   = document.getElementById("chk-save-wav");

  async function populateDevices() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const inputs = devices.filter(d => d.kind === "audioinput");

      const prevMain = deviceSelect.value;
      const prevMic  = micSelect.value;

      deviceSelect.innerHTML = '<option value="">Default device</option>';
      micSelect.innerHTML    = '<option value="">None</option>';

      for (const d of inputs) {
        const label = d.label || `Microphone ${d.deviceId.slice(0, 6)}`;

        const opt1 = document.createElement("option");
        opt1.value = d.deviceId;
        opt1.textContent = label;
        deviceSelect.appendChild(opt1);

        const opt2 = document.createElement("option");
        opt2.value = d.deviceId;
        opt2.textContent = label;
        micSelect.appendChild(opt2);
      }

      if (prevMain) deviceSelect.value = prevMain;
      if (prevMic)  micSelect.value    = prevMic;
    } catch (_) {}
  }

  populateDevices();
  navigator.mediaDevices.addEventListener("devicechange", populateDevices);

  const TARGET_RATE   = 16000;
  const SEND_EVERY_MS = 3000;

  let ws            = null;
  let audioCtx      = null;
  let sourceNode    = null;
  let micSourceNode = null;
  let workletNode   = null;
  let stream        = null;
  let micStream     = null;
  let sendTimer     = null;

  let floatChunks     = [];
  let samplesCaptured = 0;

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
    btnStart.disabled     = false;
    btnStop.disabled      = true;
    deviceSelect.disabled = false;
    micSelect.disabled    = false;
    chkSaveWav.disabled   = false;
  }

  function openSocket() {
    return new Promise((resolve, reject) => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        console.log("[transcriber] WebSocket open");
        ws.send(JSON.stringify({ type: "config", save_wav: chkSaveWav.checked }));
        resolve();
      };
      ws.onerror = () => {
        setStatus("", "WebSocket error — is the server running?");
        reject();
      };
      ws.onclose = (evt) => {
        if (statusDot.className === "recording") {
          console.warn(`[transcriber] WebSocket closed unexpectedly (code ${evt.code}) — stopping timer`);
          clearInterval(sendTimer);
          sendTimer = null;
          setStatus("", "Connection lost — server may have crashed. Stop and restart recording.");
        }
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

    let peak = 0;
    for (let i = 0; i < merged.length; i++) {
      const abs = Math.abs(merged[i]);
      if (abs > peak) peak = abs;
    }
    console.log(`[transcriber] flush peak amplitude: ${peak.toFixed(4)} (${merged.length} float32 samples @ ${audioCtx.sampleRate} Hz)`);
    if (peak < 0.001) console.warn("[transcriber] WARNING: near-silent audio — check mic permissions or hardware");

    const pcm16 = toInt16PCM(merged, audioCtx.sampleRate);
    ws.send(pcm16.buffer);
  }

  btnStart.addEventListener("click", async () => {
    const selectedDeviceId = deviceSelect.value;
    const selectedMicId    = micSelect.value;

    const baseConstraints = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

    // Open the main audio source (meeting audio / BlackHole)
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { ...baseConstraints, ...(selectedDeviceId ? { deviceId: { exact: selectedDeviceId } } : {}) },
        video: false,
      });
    } catch (e) {
      setStatus("", "Meeting audio source access denied");
      return;
    }

    // Open microphone if one is selected
    if (selectedMicId) {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: { ...baseConstraints, deviceId: { exact: selectedMicId } },
          video: false,
        });
      } catch (e) {
        console.warn("[transcriber] mic access denied — continuing without microphone", e);
        micStream = null;
      }
    }

    deviceSelect.disabled = true;
    micSelect.disabled    = true;
    chkSaveWav.disabled   = true;

    setTranscript("");
    saveNotice.classList.add("hidden");
    samplesCaptured = 0;
    floatChunks     = [];

    try {
      await openSocket();
    } catch {
      stream.getTracks().forEach(t => t.stop());
      micStream?.getTracks().forEach(t => t.stop());
      return;
    }

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") await audioCtx.resume();
    console.log("[transcriber] AudioContext sampleRate:", audioCtx.sampleRate);

    try {
      await audioCtx.audioWorklet.addModule("/static/worklet-processor.js");
    } catch (err) {
      console.error("[transcriber] failed to load AudioWorklet:", err);
      setStatus("", "Audio init failed — see console");
      stream.getTracks().forEach(t => t.stop());
      micStream?.getTracks().forEach(t => t.stop());
      resetUI();
      return;
    }

    workletNode = new AudioWorkletNode(audioCtx, "pcm-worklet");
    workletNode.port.onmessage = (e) => {
      const batch = e.data;
      if (!(batch instanceof Float32Array) || batch.length === 0) return;
      floatChunks.push(batch);
      samplesCaptured += batch.length;
    };

    // Connect sources directly to worklet — Web Audio sums them automatically
    sourceNode = audioCtx.createMediaStreamSource(stream);
    sourceNode.connect(workletNode);

    if (micStream) {
      micSourceNode = audioCtx.createMediaStreamSource(micStream);
      micSourceNode.connect(workletNode);
      console.log("[transcriber] microphone mixed in");
    }

    workletNode.connect(audioCtx.destination);

    sendTimer = setInterval(() => {
      console.log(`[transcriber] tick — captured ${samplesCaptured} samples so far`);
      flushAudio();
    }, SEND_EVERY_MS);

    const sources = micStream ? "meeting audio + microphone" : "meeting audio only";
    setStatus("recording", `Recording… (${sources})`);
    btnStart.disabled = true;
    btnStop.disabled  = false;
  });

  btnStop.addEventListener("click", async () => {
    setStatus("processing", "Processing…");
    btnStop.disabled = true;

    clearInterval(sendTimer);
    sendTimer = null;

    if (workletNode)   { workletNode.port.onmessage = null; workletNode.disconnect(); }
    if (sourceNode)    sourceNode.disconnect();
    if (micSourceNode) { micSourceNode.disconnect(); micSourceNode = null; }
    if (stream)        stream.getTracks().forEach(t => t.stop());
    if (micStream)     { micStream.getTracks().forEach(t => t.stop()); micStream = null; }

    flushAudio();
    console.log(`[transcriber] stop — captured ${samplesCaptured} samples total`);
    if (audioCtx) { await audioCtx.close(); audioCtx = null; }

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("SAVE");
    } else {
      setStatus("", "Connection was lost — transcript not saved. Reload and try again.");
      resetUI();
    }
  });
})();

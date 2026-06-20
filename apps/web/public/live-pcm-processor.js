// AudioWorklet — 16kHz mono int16 PCM downsample for Live v4 WebSocket STT.
class LivePcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / 16000;
    this._carry = 0;
    this._carryFrac = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }
    const channel = input[0];
    const out = [];
    for (let i = 0; i < channel.length; i++) {
      this._carryFrac += 1;
      if (this._carryFrac >= this._ratio) {
        this._carryFrac -= this._ratio;
        const s = Math.max(-1, Math.min(1, channel[i]));
        out.push(s < 0 ? s * 0x8000 : s * 0x7fff);
      }
    }
    if (out.length > 0) {
      const buf = new Int16Array(out);
      this.port.postMessage(buf.buffer, [buf.buffer]);
    }
    return true;
  }
}

registerProcessor("live-pcm-processor", LivePcmProcessor);

(function (global) {
  const DEFAULT_MODEL = 'lfm3-vl:2b';
  const REQUEST_TIMEOUT_MS = 120000;
  const PROMPT = [
    'Read every visible word on this cropped road sign exactly as printed.',
    'Preserve original capitalization, punctuation, numbers, and line breaks.',
    'Do not omit small words such as DO. Do not guess or invent obscured text.',
    'Return only the sign text. If no text is legible, return exactly UNREADABLE.'
  ].join(' ');
  const CONTEXT_PROMPT = [
    'Image 1 is a close crop of a road sign. Image 2 is the source street-level image for context.',
    'Read every visible word on the sign in Image 1 exactly as printed.',
    'Preserve capitalization and line breaks. Do not omit small words such as DO. Do not guess or invent obscured text.',
    'Return only the sign text. If no text is legible, return exactly UNREADABLE.'
  ].join(' ');

  function endpoint() {
    if (global.VISION_OCR_URL) return String(global.VISION_OCR_URL).replace(/\/$/, '');
    const host = global.location?.hostname || '127.0.0.1';
    return `http://${host}:11434`;
  }

  function model() {
    const queryModel = global.location?.search
      ? new URLSearchParams(global.location.search).get('ocrModel')
      : null;
    return queryModel || global.VISION_OCR_MODEL || DEFAULT_MODEL;
  }

  function cleanText(value) {
    let text = String(value || '').trim();
    text = text.replace(/^```(?:text)?\s*/i, '').replace(/\s*```$/, '').trim();
    if (/^UNREADABLE\.?$/i.test(text)) return '';
    if (text.length > 1 && ((text[0] === '"' && text.at(-1) === '"') || (text[0] === "'" && text.at(-1) === "'"))) {
      text = text.slice(1, -1).trim();
    }
    return text;
  }

  function encode(source) {
    if (source?.toDataURL) return source.toDataURL('image/jpeg', 0.92).split(',', 2)[1];
    if (!source?.naturalWidth || !source?.naturalHeight) return '';
    const scale = Math.min(1, 1200 / Math.max(source.naturalWidth, source.naturalHeight));
    const context = document.createElement('canvas');
    context.width = Math.max(1, Math.round(source.naturalWidth * scale));
    context.height = Math.max(1, Math.round(source.naturalHeight * scale));
    context.getContext('2d').drawImage(source, 0, 0, context.width, context.height);
    return context.toDataURL('image/jpeg', 0.88).split(',', 2)[1];
  }

  async function recognize(canvas, sourceImage = null) {
    const image = encode(canvas);
    if (!image) throw Error('The sign crop could not be encoded.');
    const contextImage = encode(sourceImage);
    const images = contextImage ? [image, contextImage] : [image];

    const started = performance.now();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch(`${endpoint()}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          model: model(),
          messages: [{ role: 'user', content: contextImage ? CONTEXT_PROMPT : PROMPT, images }],
          think: false,
          stream: false,
          options: {
            temperature: 0.1,
            top_p: 1,
            top_k: 50,
            min_p: 0,
            repeat_penalty: 1.1,
            num_predict: 160
          }
        })
      });
      if (!response.ok) {
        let detail = '';
        try {
          detail = (await response.json()).error || '';
        } catch {}
        throw Error(detail || `Ollama returned HTTP ${response.status}.`);
      }
      const data = await response.json();
      return {
        text: cleanText(data.message?.content ?? data.response),
        model: model(),
        elapsedMs: Math.round(performance.now() - started)
      };
    } finally {
      clearTimeout(timer);
    }
  }

  global.VisionOCR = { cleanText, endpoint, model, recognize };
})(window);

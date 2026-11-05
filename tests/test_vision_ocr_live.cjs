const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const endpoint = process.env.VISION_OCR_URL || 'http://127.0.0.1:11434';
const model = process.env.VISION_OCR_MODEL || 'lfm3-vl:2b';
const prompt = 'Read every visible word on this image exactly as printed. Do not guess obscured text. Return only the visible text, or UNREADABLE.';
const cases = [
  ['stop-clear', '26277391155284674_right_0.jpg', 'STOP'],
  ['stop-small', '1990021664930867_front_0.jpg', 'STOP'],
  ['road-work', '1662454378222713_back_1.jpg', 'END ROAD WORK DOUBLE FINES END'],
  ['do-not-enter', '2306517029836285_front_0.jpg', 'DO NOT ENTER', '../../views/mapillary/2306517029836285_front.jpg']
];

const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();

(async () => {
  const tags = await fetch(`${endpoint}/api/tags`).then(response => response.json());
  assert.ok(tags.models?.some(item => item.name === model), `Install the OCR model first: ollama pull ${model}`);

  for (const [name, file, expected, contextFile] of cases) {
    const imagePath = path.resolve(__dirname, '..', 'data', 'wellesley', 'crops', 'mapillary', file);
    const images = [fs.readFileSync(imagePath).toString('base64')];
    if (contextFile) {
      images.push(fs.readFileSync(path.resolve(path.dirname(imagePath), contextFile)).toString('base64'));
    }
    const started = Date.now();
    const response = await fetch(`${endpoint}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        stream: false,
        think: false,
        messages: [{
          role: 'user',
          content: contextFile
            ? 'Image 1 is a close crop of a road sign. Image 2 is the source street-level image for context. Read the exact words on the sign in Image 1, including small words such as DO. Return only the sign text.'
            : prompt,
          images
        }],
        options: { temperature: 0.1, num_predict: 80 }
      })
    });
    const result = await response.json();
    assert.equal(response.status, 200, result.error);
    assert.equal(normalize(result.message?.content), expected, `${name} OCR mismatch`);
    console.log(`${name}: ${expected} (${Date.now() - started} ms)`);
  }
})().catch(error => {
  console.error(error);
  process.exit(1);
});

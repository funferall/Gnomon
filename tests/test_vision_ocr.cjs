const assert = require('node:assert/strict');
global.window = global;
global.location = { hostname: '127.0.0.1', search: '' };
global.performance = { now: () => 25 };

let request;
global.fetch = async (url, options) => {
  request = { url, options, body: JSON.parse(options.body) };
  return {
    ok: true,
    json: async () => ({ message: { content: '```text\nEND ROAD WORK\nDOUBLE FINES END\n```' } })
  };
};

require('../static/vision-ocr.js');

(async () => {
  assert.equal(VisionOCR.model(), 'lfm3-vl:2b');
  assert.equal(VisionOCR.endpoint(), 'http://127.0.0.1:11434');
  assert.equal(VisionOCR.cleanText('UNREADABLE.'), '');
  assert.equal(VisionOCR.cleanText('"STOP"'), 'STOP');

  const canvas = { toDataURL: () => 'data:image/jpeg;base64,AP8=' };
  const result = await VisionOCR.recognize(canvas);
  assert.equal(request.url, 'http://127.0.0.1:11434/api/chat');
  assert.equal(request.body.model, 'lfm3-vl:2b');
  assert.equal(request.body.think, false);
  assert.deepEqual(request.body.messages[0].images, ['AP8=']);
  assert.match(request.body.messages[0].content, /exactly as printed/);
  assert.equal(result.text, 'END ROAD WORK\nDOUBLE FINES END');
  assert.equal(result.model, 'lfm3-vl:2b');
  console.log('Vision OCR request and response checks passed');
})().catch(error => {
  console.error(error);
  process.exit(1);
});

"""Model access for the regulations pipeline: OpenAI gpt-6-luna only (organisation policy: OpenAI).

call(provider, system, text, schema, images) -> {'data', 'raw', 'usage', 'cost_usd', 'latency_s', 'model', 'error'}
Output is constrained with a strict JSON schema. The key comes from OPENAI_API_KEY and is never logged.
Price: USD 0.10 / 0.50 per 1M input / output tokens (developers.openai.com, checked 2026-11-05).

A three-way comparison on 2026-11-05 (gpt-6-luna, claude-haiku-5-5, deepseek-flash) chose gpt-6-luna: highest accuracy
on the free-form schedules (99.5%), lowest cost ($0.002 per document), no failed runs. Results: REGULATIONS_PLAN.md.
"""
import base64, json, time

MODELS = {'openai': 'gpt-6-luna'}
PRICES = {'gpt-6-luna': (0.10, 0.50)}
_client = None


def client():
    global _client
    if _client is None:
        import openai; _client = openai.OpenAI(max_retries=3, timeout=180)
    return _client


def call(provider, system, text, schema, images=(), max_tokens=16000, schema_name='result'):
    """images: list of (bytes, media_type). Returns parsed JSON in 'data' or an 'error' string."""
    if provider not in MODELS: raise ValueError(f'Unsupported provider {provider!r}; this pipeline uses OpenAI only')
    model = MODELS[provider]; t0 = time.perf_counter(); out = {'provider': provider, 'model': model}
    try:
        content = [{'type': 'image_url', 'image_url': {'url': f'data:{mt};base64,{base64.standard_b64encode(b).decode("ascii")}'}} for b, mt in images] + [{'type': 'text', 'text': text}]
        r = client().chat.completions.create(model=model, messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                                             response_format={'type': 'json_schema', 'json_schema': {'name': schema_name, 'schema': schema, 'strict': True}},
                                             max_completion_tokens=max_tokens)
        ch = r.choices[0]
        if ch.finish_reason == 'length': raise RuntimeError('max_tokens reached')
        raw = ch.message.content or ''; usage = {'input': r.usage.prompt_tokens, 'output': r.usage.completion_tokens}
        pin, pout = PRICES[model]
        out.update(raw=raw, data=json.loads(raw), usage=usage, cost_usd=(usage['input'] * pin + usage['output'] * pout) / 1e6)
    except Exception as e:  # never include request objects (they can carry keys)
        out['error'] = f'{type(e).__name__}: {str(e)[:300]}'
    out['latency_s'] = round(time.perf_counter() - t0, 2); return out

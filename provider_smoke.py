"""Opt-in, read-only provider checks. Never prints credentials or response bodies."""
import json
import os
from pathlib import Path
import tomllib

import requests


def main():
    secret_path = Path(__file__).parent / '.streamlit' / 'secrets.toml'
    secrets = tomllib.loads(secret_path.read_text(encoding='utf-8')) if secret_path.exists() else {}
    token = os.environ.get('UPSTOX_TOKEN') or secrets.get('UPSTOX_TOKEN')
    api_key = os.environ.get('GEMINI_API_KEY') or secrets.get('GEMINI_API_KEY')
    report = {'upstox_configured': bool(token), 'gemini_configured': bool(api_key)}
    if token:
        for exchange in ('NSE', 'MCX'):
            try:
                response = requests.get(f'https://api.upstox.com/v2/market/status/{exchange}',
                                        headers={'Authorization':f'Bearer {token}', 'Accept':'application/json'}, timeout=(3,6))
                report[exchange] = {'http':response.status_code}
                if response.ok:
                    report[exchange]['status'] = response.json().get('data',{}).get('status')
                response.close()
            except Exception as exc:
                report[exchange] = {'error':type(exc).__name__}
    if api_key:
        try:
            from google import genai
            from google.genai import types
            with genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=15000)) as client:
                available = {str(m.name).removeprefix('models/') for m in client.models.list()}
                preferred = [secrets.get('GEMINI_MODEL', 'gemini-3.7-flash'), 'gemini-3.6-flash']
                report['gemini_available_candidates'] = [m for m in preferred if m in available]
                # No portfolio/account data is sent; this is a tiny connectivity/arithmetic test.
                if '--generate' in __import__('sys').argv and report['gemini_available_candidates']:
                    result = client.models.generate_content(model=report['gemini_available_candidates'][0],
                        contents='Return only the number: 2 + 2.',
                        config=types.GenerateContentConfig(max_output_tokens=128, temperature=0))
                    report['gemini_arithmetic_ok'] = (result.text or '').strip() == '4'
        except Exception as exc:
            report['gemini_error'] = type(exc).__name__
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

"""Review the exact upgraded profile and its generated PNG display path."""
from importlib import metadata
from pathlib import Path
import io

from PIL import Image
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
PINS = {'streamlit': '1.66.1', 'pillow': '13.0.0', 'certifi': '2026.10.23',
        'opentelemetry-api': '1.45.1', 'opentelemetry-sdk': '1.45.1',
        'opentelemetry-exporter-otlp-proto-http': '1.45.1',
        'opentelemetry-proto': '1.45.1',
        'opentelemetry-exporter-otlp-proto-common': '1.45.1',
        'opentelemetry-semantic-conventions': '0.66b1',
        'opentelemetry-exporter-http-transport': '0.66b1',
        'opentelemetry-exporter-otlp-common': '0.66b1'}


def test_exact_reviewed_security_profile_is_installed_and_constrained():
    lines = (ROOT / 'constraints.txt').read_text(encoding='utf-8').splitlines()
    for name, version in PINS.items():
        assert lines.count(name + '==' + version) == 1
        assert metadata.version(name) == version


def test_forward_helper_pin_matches_reviewed_app_profile_only():
    from future_ops_diagnostics import PINS as forward_pins
    assert forward_pins['certifi'] == PINS['certifi']
    assert 'certifi==' + PINS['certifi'] in (ROOT / 'requirements-forward-operations.txt').read_text()


def test_generated_png_roundtrip_is_exact():
    pixels = Image.new('RGB', (2, 2), (10, 20, 30))
    output = io.BytesIO()
    pixels.save(output, format='PNG')
    with Image.open(io.BytesIO(output.getvalue())) as decoded:
        decoded.load()
        assert decoded.size == (2, 2)
        assert decoded.getpixel((0, 0)) == (10, 20, 30)


def test_new_streamlit_accepts_generated_chart_and_png_offline():
    app = AppTest.from_string('''
import streamlit as st
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
st.image(Image.new('RGB', (2, 2), (10, 20, 30)))
fig, ax = plt.subplots()
ax.plot([0, 1], [0, 1])
st.pyplot(fig)
plt.close(fig)
''').run(timeout=20)
    assert not app.exception

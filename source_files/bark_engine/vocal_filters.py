"""FFmpeg vocal processing filter chains for each vocal style."""

from __future__ import annotations

from typing import Final

from bark_engine.models import VocalStyle

VOCAL_FILTERS: Final[dict[VocalStyle, list[str]]] = {
    VocalStyle.SINGING: [
        "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
        "equalizer=f=120:t=h:w=120:g=-4",
        "equalizer=f=2500:t=h:w=2000:g=4",
        "equalizer=f=6000:t=h:w=3000:g=3",
        "equalizer=f=10000:t=h:w=2000:g=2",
        "aecho=0.6:0.5:25|45:0.2|0.12",
        "volume=1.3",
    ],
    VocalStyle.RAP: [
        "acompressor=threshold=-14dB:ratio=5:attack=2:release=35",
        "equalizer=f=100:t=h:w=100:g=-5",
        "equalizer=f=2500:t=h:w=2000:g=5",
        "equalizer=f=6000:t=h:w=3000:g=4",
        "aecho=0.6:0.5:15|25:0.2|0.1",
        "volume=1.5",
    ],
    VocalStyle.SPOKEN: [
        "acompressor=threshold=-15dB:ratio=4:attack=3:release=50",
        "equalizer=f=2000:t=h:w=1500:g=3",
        "equalizer=f=5000:t=h:w=2000:g=2",
        "aecho=0.8:0.85:35|55:0.2|0.12",
        "volume=1.2",
    ],
    VocalStyle.SHOUT: [
        "acompressor=threshold=-12dB:ratio=6:attack=1:release=25",
        "equalizer=f=100:t=h:w=100:g=-6",
        "equalizer=f=3000:t=h:w=2000:g=6",
        "equalizer=f=8000:t=h:w=3000:g=5",
        "aecho=0.5:0.4:10|20|35:0.25|0.18|0.1",
        "volume=1.6",
    ],
    VocalStyle.WHISPER: [
        "acompressor=threshold=-20dB:ratio=2:attack=8:release=100",
        "equalizer=f=200:t=h:w=200:g=-3",
        "equalizer=f=4000:t=h:w=2000:g=5",
        "equalizer=f=10000:t=h:w=3000:g=3",
        "aecho=0.8:0.9:50|80:0.3|0.2",
        "volume=0.9",
    ],
    VocalStyle.EPIC: [
        "acompressor=threshold=-15dB:ratio=4:attack=3:release=50",
        "equalizer=f=2000:t=h:w=2000:g=4",
        "equalizer=f=8000:t=h:w=3000:g=3",
        "aecho=0.7:0.6:40|70|100:0.3|0.2|0.1",
        "volume=1.2",
    ],
}

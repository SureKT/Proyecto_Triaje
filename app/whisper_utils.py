"""
app/whisper_utils.py
Transcripción de audio a texto usando faster-whisper (CPU/GPU).
"""
from faster_whisper import WhisperModel

_model = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        # 'small' equilibra velocidad y precisión para español en CPU
        # Cambiar a 'medium' si hay GPU disponible
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def transcribe_audio(audio_bytes: bytes) -> str:
    """
    Recibe el contenido binario de un fichero de audio y devuelve el texto transcrito.
    Soporta .wav, .mp3, .m4a y cualquier formato que ffmpeg pueda leer.
    """
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        model = _get_model()
        segments, _ = model.transcribe(tmp_path, language="es", beam_size=5)
        return " ".join(seg.text.strip() for seg in segments)
    finally:
        os.unlink(tmp_path)

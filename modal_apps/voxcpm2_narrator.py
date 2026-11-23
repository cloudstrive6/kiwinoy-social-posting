"""Backup narrator: VoxCPM2 cloning "BOSS KG Guide C" on a Modal L4 (Bryce, 2026-11-23).

Used only when the month's ElevenLabs credits cannot voice a new video (tools/analysis_narrate.py,
KG_NARRATOR=auto or voxcpm2). Settings are take 1 of the 2026-11-23 listening test, which Bryce
picked by ear: seed 11, cfg_value 2.0, 10 inference steps, the 12 s Guide C prompt plus its text,
and the full Guide C clip as the reference. VoxCPM2 is Apache-2.0 (weights and code).

Storage: the Modal Volume "kg-voxcpm2" holds the weights (downloaded once from Hugging Face into
/vol/hf) and the Guide C reference files (/vol/refs/, uploaded by the voice-backup-deploy step of
analysis-longform.yml from B2 voice-refs/guide-c/). Nothing private is baked into the image.

Shape: Modal's chatterbox_tts.py example (MIT): one class, the model loaded once per container in
@modal.enter, paragraphs fanned out with .starmap over up to 4 containers.

    modal deploy modal_apps/voxcpm2_narrator.py
    modal run modal_apps/voxcpm2_narrator.py::warm      # downloads the weights into the Volume
"""
from __future__ import annotations

import modal

APP_NAME = "kg-voxcpm2-narrator"
VOLUME = "kg-voxcpm2"
REFS = "/vol/refs"
SETTINGS = {"cfg_value": 2.0, "inference_timesteps": 10}

app = modal.App(APP_NAME)
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)

# Pins: the versions that ran take 1 locally (voxcpm 2.0.3, torch 2.10.0, torchcodec 0.17.0,
# transformers 5.23.0). Locally torch was the cu130 build; here it is cu128, which Modal's drivers run
# everywhere, and the parity test checks the result. torch and torchaudio are pinned again in the
# second install so voxcpm's other dependencies cannot swap them. torchcodec must match torch (VoxCPM
# issue #119); optimize=True needs a C compiler (#419), so it stays off.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "libsndfile1")
    .pip_install("torch==2.10.0", "torchaudio==2.10.0", index_url="https://download.pytorch.org/whl/cu128")
    .pip_install("torch==2.10.0", "torchaudio==2.10.0", "torchcodec==0.17.0", "voxcpm==2.0.3",
                 "transformers==5.23.0", "soundfile", "numpy", "huggingface_hub",
                 extra_index_url="https://download.pytorch.org/whl/cu128")
    .env({"HF_HOME": "/vol/hf", "HF_HUB_DISABLE_TELEMETRY": "1"})
)


@app.cls(gpu="L4", image=image, volumes={"/vol": vol}, timeout=1800, scaledown_window=120,
         max_containers=4)
class Narrator:
    @modal.enter()
    def load(self) -> None:
        import time
        from pathlib import Path

        from voxcpm import VoxCPM
        t0 = time.time()
        self.model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False, optimize=False,
                                            device="cuda")
        vol.commit()  # keeps the weights if this container downloaded them
        self.sr = self.model.tts_model.sample_rate
        self.prompt_wav = f"{REFS}/guide-C_12s.wav"
        self.prompt_text = Path(f"{REFS}/guide-C_12s.txt").read_text(encoding="utf-8").strip()
        self.ref_full = f"{REFS}/guide-C_full.wav"
        for f in (self.prompt_wav, self.ref_full):
            if not Path(f).exists():
                raise RuntimeError(f"{f} missing on the Volume: run the voice-backup-deploy step")
        self.load_s = round(time.time() - t0, 1)
        print(f"VoxCPM2 loaded in {self.load_s} s, {self.sr} Hz", flush=True)

    @modal.method()
    def narrate_one(self, pid: str, text: str, seed: int = 11) -> dict:
        """One paragraph: {"id", "seed", "wav" (16-bit PCM WAV bytes), "render_s", "audio_s", "load_s"}."""
        import io
        import time

        import soundfile as sf
        import torch
        torch.manual_seed(int(seed))
        t = time.time()
        wav = self.model.generate(text=text, prompt_wav_path=self.prompt_wav, prompt_text=self.prompt_text,
                                  reference_wav_path=self.ref_full, **SETTINGS)
        buf = io.BytesIO()
        # float output kept as float: the QC on the runner checks the raw peak before any mastering
        sf.write(buf, wav, self.sr, format="WAV", subtype="FLOAT")
        return {"id": pid, "seed": int(seed), "wav": buf.getvalue(), "render_s": round(time.time() - t, 2),
                "audio_s": round(len(wav) / self.sr, 2), "load_s": self.load_s}


@app.function(image=image, volumes={"/vol": vol}, timeout=1800)
def warm() -> str:
    """Download the weights into the Volume once (CPU only, no GPU billed)."""
    from huggingface_hub import snapshot_download
    path = snapshot_download("openbmb/VoxCPM2")
    vol.commit()
    return path

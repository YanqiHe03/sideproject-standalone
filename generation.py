"""Load the model once; keep each stream's text context and pacing independent."""

import logging
import random
import time

import settings

logger = logging.getLogger(__name__)


class GenerationEngine:
    def __init__(self, model, tokenizer, device, pca, osc_sender):
        self.model = model
        self.tokenizer = tokenizer
        self.device = device
        self.pca = pca
        self.osc_sender = osc_sender
        self._osc_failed = False

    @classmethod
    def load(cls):
        """Load weights and calibrate PCA at server startup, never on import.

        Model/calibration errors deliberately fail startup: a server that cannot
        generate should not announce itself as ready.
        """
        import numpy as np
        import torch
        from pythonosc import udp_client
        from sklearn.decomposition import PCA
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if torch.backends.mps.is_available():
            device = torch.device("mps")
        elif torch.cuda.is_available():
            device = torch.device("cuda")
        else:
            device = torch.device("cpu")

        logger.info("Loading %s on %s", settings.MODEL_DIR, device)
        tokenizer = AutoTokenizer.from_pretrained(
            settings.MODEL_DIR, trust_remote_code=True
        )
        model = AutoModelForCausalLM.from_pretrained(
            settings.MODEL_DIR, trust_remote_code=True, torch_dtype=torch.float32
        ).to(device)
        model.eval()

        logger.info("Calibrating latent space (PCA)")
        calibration_vectors = []
        with torch.no_grad():
            for sentence in settings.CALIBRATION_SENTENCES:
                inputs = tokenizer(sentence, return_tensors="pt")
                inputs = {key: value.to(device) for key, value in inputs.items()}
                outputs = model(**inputs, output_hidden_states=True)
                hidden = outputs.hidden_states[-1].squeeze(0).cpu().float().numpy()
                calibration_vectors.append(hidden)
        pca = PCA(n_components=3)
        pca.fit(np.concatenate(calibration_vectors, axis=0))

        try:
            osc_sender = udp_client.SimpleUDPClient(
                settings.OSC_TARGET_IP, settings.OSC_TARGET_PORT
            )
        except Exception:
            # OSC is an optional output; unavailable networking must not prevent
            # the text installation from starting.
            logger.exception("OSC client unavailable; text generation remains enabled")
            osc_sender = None

        logger.info(
            "Model ready; OSC target %s:%s",
            settings.OSC_TARGET_IP,
            settings.OSC_TARGET_PORT,
        )
        return cls(model, tokenizer, device, pca, osc_sender)

    def _send_osc(self, address, payload):
        if self.osc_sender is None:
            return False
        try:
            self.osc_sender.send_message(address, payload)
        except Exception:
            # Log once per outage, but keep trying on subsequent tokens so a
            # transient send failure can recover without restarting generation.
            if not self._osc_failed:
                logger.exception("OSC send failed; text generation will continue")
            self._osc_failed = True
            return False
        if self._osc_failed:
            logger.info("OSC sending recovered")
        self._osc_failed = False
        return True

    def reset_output(self, value=1):
        """Send an OSC reset only; this does not restart any text stream."""
        return self._send_osc("/reset", value)

    def generate(self, *, temp, context, delay, reset):
        """Yield seed/token records until the caller stops consuming the stream."""
        import torch

        if reset:
            self.reset_output()

        seed_text = random.choice(settings.SEEDS)
        inputs = self.tokenizer(text=seed_text, return_tensors="pt")
        input_ids = inputs.input_ids.to(self.device)
        count = 0
        max_context = max(1, context)
        pause = max(0.01, min(2.0, delay))
        yield {"text": seed_text, "count": 0}

        while True:
            if count >= settings.MAX_TOKENS_BEFORE_RESET:
                seed_text = random.choice(settings.SEEDS)
                inputs = self.tokenizer(text=seed_text, return_tensors="pt")
                input_ids = inputs.input_ids.to(self.device)
                count = 0
                self.reset_output()
                yield {"text": f"\n\n[AUTO-RESET: MEMORY FLUSH]\n{seed_text}", "count": 0}
                continue

            if input_ids.shape[1] > max_context:
                input_ids = input_ids[:, -max_context:]

            with torch.no_grad():
                outputs = self.model(input_ids=input_ids, output_hidden_states=True)
                logits = outputs.logits[:, -1, :]
                last_hidden = outputs.hidden_states[-1][0, -1, :].cpu().float().numpy()
                xyz = self.pca.transform([last_hidden])[0]
                logits = logits / temp

                sorted_logits, sorted_indices = torch.sort(logits, descending=True)
                cumulative_probs = torch.softmax(sorted_logits, dim=-1).cumsum(dim=-1)
                sorted_remove = cumulative_probs > settings.TOP_P
                sorted_remove[..., 1:] = sorted_remove[..., :-1].clone()
                sorted_remove[..., 0] = False
                remove = sorted_remove.scatter(1, sorted_indices, sorted_remove)
                logits[remove] = -float("inf")

                probs = torch.softmax(logits, dim=-1)
                next_token = torch.multinomial(probs, num_samples=1)
                final_prob = probs[0, next_token[0].item()].item()
                top_probs, top_indices = torch.topk(probs, k=settings.TOP_CANDIDATES, dim=-1)
                candidates = [
                    {
                        "token": self.tokenizer.decode(
                            [top_indices[0, i].item()], skip_special_tokens=False
                        ),
                        "prob": round(top_probs[0, i].item(), 4),
                    }
                    for i in range(settings.TOP_CANDIDATES)
                ]

            text = self.tokenizer.decode(next_token[0], skip_special_tokens=False)
            count += 1
            yield {
                "text": text,
                "count": count,
                "candidates": candidates,
                "final_prob": round(final_prob, 6),
            }
            self._send_osc(
                "/latent/point",
                [text, float(xyz[0]), float(xyz[1]), float(xyz[2]), count],
            )
            input_ids = torch.cat([input_ids, next_token], dim=-1)
            time.sleep(pause)

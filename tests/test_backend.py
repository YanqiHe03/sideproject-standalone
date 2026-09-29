"""Backend behavior checks with real tensor sampling and no downloaded model/USB."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch

from app import create_app
from generation import GenerationEngine


class TinyTokenizer:
    def __call__(self, text, return_tensors):
        return SimpleNamespace(input_ids=torch.tensor([[0]]))

    def decode(self, ids, skip_special_tokens):
        tokens = ["A", "字", "<|endoftext|>", "B", "C", "D"]
        return "".join(
            tokens[int(i)] for i in ids if not (skip_special_tokens and int(i) == 2)
        )


class TinyModel:
    def __init__(self, logits=None):
        self.logits = logits if logits is not None else [-100, -100, 100, -100, -100, -100]
        self.contexts = []

    def __call__(self, input_ids, output_hidden_states):
        self.contexts.append(input_ids.tolist()[0])
        return SimpleNamespace(
            logits=torch.tensor([[self.logits]], dtype=torch.float32),
            hidden_states=[torch.ones(1, input_ids.shape[1], 3)],
        )


class OscRecorder:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_message(self, address, payload):
        self.messages.append((address, payload))
        if self.fail:
            raise OSError("test: OSC network unavailable")


def engine_with(model=None, osc=None):
    return GenerationEngine(
        model or TinyModel(), TinyTokenizer(), torch.device("cpu"),
        SimpleNamespace(transform=lambda values: [[1.0, 2.0, 3.0]]),
        osc if osc is not None else OscRecorder(),
    )


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.sleep = self.enterContext(patch("generation.time.sleep"))
        self.enterContext(patch("generation.random.choice", return_value="A"))

    def stream(self, engine, **options):
        params = dict(temp=1.0, context=2, delay=0.1, reset=True)
        params.update(options)
        stream = engine.generate(**params)
        self.addCleanup(stream.close)
        return stream

    def test_special_tokens_candidates_context_and_osc_match_stream(self):
        model, osc = TinyModel(), OscRecorder()
        stream = self.stream(engine_with(model, osc))
        records = [next(stream) for _ in range(4)]
        self.assertEqual(records[0], {"text": "A", "count": 0})
        self.assertEqual([r["count"] for r in records], [0, 1, 2, 3])
        self.assertEqual([r["text"] for r in records[1:]], ["<|endoftext|>"] * 3)
        self.assertEqual(len(records[1]["candidates"]), 5)
        self.assertEqual(records[1]["candidates"][0], {"token": "<|endoftext|>", "prob": 1.0})
        self.assertEqual(records[1]["final_prob"], 1.0)
        self.assertEqual(model.contexts, [[0], [0, 2], [2, 2]])
        self.assertEqual(osc.messages[0], ("/reset", 1))
        self.assertEqual(osc.messages[1], ("/latent/point", ["<|endoftext|>", 1.0, 2.0, 3.0, 1]))

    def test_temperature_and_top_p_keep_the_crossing_token(self):
        # At temperature 1, nucleus sampling must retain the token that crosses
        # 0.92 (0.90 + 0.08); the low-probability tail must be filtered out.
        logits = torch.log(torch.tensor([0.9, 0.08, 0.005, 0.005, 0.005, 0.005])).tolist()
        stream = self.stream(engine_with(TinyModel(logits)), temp=1.0)
        next(stream)
        record = next(stream)
        probabilities = {c["token"]: c["prob"] for c in record["candidates"]}
        self.assertEqual(probabilities["A"], 0.9184)
        self.assertEqual(probabilities["字"], 0.0816)
        self.assertEqual(sum(p > 0 for p in probabilities.values()), 2)
        colder = self.stream(engine_with(TinyModel(logits)), temp=0.5)
        next(colder)
        cold_record = next(colder)
        self.assertEqual(cold_record["text"], "A")
        self.assertEqual(cold_record["final_prob"], 1.0)

    def test_each_stream_uses_its_own_delay_and_count(self):
        engine = engine_with()
        fast = self.stream(engine, delay=0.1)
        slow = self.stream(engine, delay=1.0)
        for stream in (fast, slow):
            self.assertEqual(next(stream)["count"], 0)
            self.assertEqual(next(stream)["count"], 1)
        self.assertEqual(next(fast)["count"], 2)
        self.assertEqual(next(slow)["count"], 2)
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [0.1, 1.0])

    def test_delay_clamping_is_preserved(self):
        for delay, expected in [(0, 0.01), (10, 2.0)]:
            with self.subTest(delay=delay):
                stream = self.stream(engine_with(), delay=delay)
                for _ in range(3):
                    next(stream)
                self.assertEqual(self.sleep.call_args.args, (expected,))

    def test_memory_flush_keeps_stream_open_and_restarts_model_context(self):
        model, osc = TinyModel(), OscRecorder()
        with patch("settings.MAX_TOKENS_BEFORE_RESET", 2):
            stream = self.stream(engine_with(model, osc))
            records = [next(stream) for _ in range(5)]
        self.assertEqual([r["count"] for r in records], [0, 1, 2, 0, 1])
        self.assertEqual(records[3]["text"], "\n\n[AUTO-RESET: MEMORY FLUSH]\nA")
        self.assertEqual(model.contexts, [[0], [0, 2], [0]])
        self.assertEqual([m for m in osc.messages if m[0] == "/reset"], [("/reset", 1)] * 2)

    def test_osc_failure_does_not_stop_text_and_sending_can_recover(self):
        osc = OscRecorder()
        osc.fail = True
        engine = engine_with(osc=osc)
        stream = self.stream(engine)
        with self.assertLogs("generation", level="ERROR") as logs:
            records = [next(stream) for _ in range(4)]
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(records[-1]["count"], 3)
        osc.fail = False
        self.assertEqual(next(stream)["count"], 4)
        self.assertTrue(engine.reset_output(9))
        self.assertEqual(osc.messages[-1], ("/reset", 9))

    def test_reset_false_and_unavailable_osc(self):
        osc = OscRecorder()
        stream = self.stream(engine_with(osc=osc), reset=False)
        for _ in range(3):
            next(stream)
        self.assertTrue(all(address == "/latent/point" for address, _ in osc.messages))
        engine = engine_with()
        engine.osc_sender = None
        self.assertFalse(engine.reset_output())
        stream = self.stream(engine)
        self.assertEqual([next(stream)["count"] for _ in range(3)], [0, 1, 2])

    def test_model_errors_propagate_instead_of_silently_ending_text(self):
        model = Mock(side_effect=RuntimeError("inference failed"))
        stream = self.stream(engine_with(model=model))
        next(stream)
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            next(stream)


async def http_request(app, path, body=None, method="POST"):
    """Exercise the ASGI interface without a separate server/client dependency."""
    payload = json.dumps(body).encode() if body is not None else b""
    messages = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(b"content-type", b"application/json"), (b"origin", b"http://localhost:8080")],
        "server": ("test", 80), "client": ("test", 1),
    }
    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), data


class HttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_loads_once_and_passes_each_request_to_engine(self):
        records = [{"text": "A", "count": 0}, {"text": "字\n<|endoftext|>", "count": 1}]
        engine = SimpleNamespace(generate=Mock(side_effect=lambda **params: iter(records)))
        loader = Mock(return_value=engine)
        app = create_app(loader)
        loader.assert_not_called()
        async with app.router.lifespan_context(app):
            for delay in (0.1, 1.0):
                params = dict(temp=0.6, context=10, delay=delay, reset=False)
                status, headers, body = await http_request(app, "/generate", params)
                self.assertEqual(status, 200)
                self.assertIn(b"application/x-ndjson", headers[b"content-type"])
                self.assertIn(
                    headers[b"access-control-allow-origin"],
                    (b"*", b"http://localhost:8080"),
                )
                self.assertEqual([json.loads(line) for line in body.splitlines()], records)
                engine.generate.assert_called_with(**params)
            loader.assert_called_once_with()

    async def test_defaults_and_invalid_settings(self):
        engine = SimpleNamespace(generate=Mock(return_value=iter([])))
        app = create_app(lambda: engine)
        async with app.router.lifespan_context(app):
            self.assertEqual((await http_request(app, "/generate", {}))[0], 200)
            engine.generate.assert_called_once_with(temp=1.0, context=64, delay=0.05, reset=True)
            engine.generate.reset_mock()
            for params in ({"temp": 0}, {"temp": -1}, {"temp": "nan"},
                           {"context": 0}, {"delay": -1}, {"delay": "inf"}):
                with self.subTest(params=params):
                    self.assertEqual((await http_request(app, "/generate", params))[0], 422)
            engine.generate.assert_not_called()

    async def test_reset_reports_send_failure_and_old_delay_route_is_gone(self):
        engine = SimpleNamespace(reset_output=Mock(side_effect=[True, False]))
        app = create_app(lambda: engine)
        async with app.router.lifespan_context(app):
            self.assertEqual((await http_request(app, "/reset", {"value": 7}))[0], 200)
            engine.reset_output.assert_called_with(7)
            status, _, body = await http_request(app, "/reset", {})
            self.assertEqual(status, 503)
            self.assertEqual(json.loads(body), {"status": "unavailable", "value": 1})
            self.assertEqual((await http_request(app, "/set-delay", {"delay": 1}))[0], 404)
            self.assertEqual((await http_request(app, "/", method="GET"))[0], 200)

    async def test_failed_model_load_fails_startup(self):
        app = create_app(Mock(side_effect=RuntimeError("weights unavailable")))
        with self.assertRaisesRegex(RuntimeError, "weights unavailable"):
            async with app.router.lifespan_context(app):
                self.fail("Startup must not complete without a model")


class ImportTests(unittest.TestCase):
    def test_import_does_not_load_model_libraries_or_start_generation(self):
        result = subprocess.run(
            [sys.executable, "-c", "import app, sys; assert 'torch' not in sys.modules; "
             "assert 'transformers' not in sys.modules; assert 'sklearn' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

"""Protocol/boundary regressions; the separate RTL suite calibrates the sampler."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kda_memory as memory
from kda_ame_memory import with_read_returns


def request(ident, stamp, source=1, opcode=4):
    return (ident, 'A', 'TLA_near_cute', stamp, stamp-3, opcode, 0, 6, source, 0x80000000, -1, 0, 0)


def returned(ident, stamp, source=1, ready=1, payload='00'*64):
    return (ident, stamp, stamp-3, source, ready, payload)


def decode(rows, returns, begin=0, end=100):
    full = memory.decode(rows)
    return with_read_returns(memory.decode(rows, begin, end), full['transactions'], returns, begin, end)


class AmeReadTests(unittest.TestCase):
    def test_payload_latency_and_outstanding(self):
        result = decode([request(1, 10), request(2, 12, 2)],
                        [returned(1, 20), returned(2, 25, 2)])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['metrics']['read_payload_bytes'], 128)
        self.assertEqual(result['metrics']['read_completion_latency'], 11.5)
        self.assertEqual(result['metrics']['read_outstanding_max'], 2)
        self.assertEqual(result['metrics']['read_outstanding_mean'], .23)
        self.assertIsNone(result['metrics']['dram_bytes'])
        self.assertEqual(result['transactions'][0]['denied'], None)

    def test_entering_and_leaving_requests_follow_return(self):
        result = decode([request(1, 10), request(2, 17, 2)],
                        [returned(1, 19), returned(2, 30, 2)], 15, 25)
        self.assertEqual(result['boundary']['entering_reads'], 1)
        self.assertEqual(result['boundary']['leaving_reads'], 1)
        self.assertEqual(result['metrics']['read_payload_bytes'], 64)
        self.assertEqual(result['transactions'][0]['response_cpu_stamp'], 30)
        self.assertEqual(len(result['read_returns']['accepted_in_interval']), 1)
        self.assertEqual(result['metrics']['read_outstanding_max'], 2)

    def test_missing_return_remains_pending(self):
        result = decode([request(1, 10)], [])
        self.assertEqual(result['boundary']['unclosed_reads_in_full_capture'], 1)
        self.assertEqual(result['metrics']['observed_read_completions'], 0)
        self.assertIsNone(result['metrics']['read_completion_latency'])
        self.assertIsNone(result['transactions'][0]['read_payload_bytes'])

    def test_reuse_after_return_on_same_cycle(self):
        result = decode([request(1, 10), request(2, 20)],
                        [returned(1, 20), returned(2, 30)])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['metrics']['observed_read_completions'], 2)

    def test_reuse_across_read_write_rejected(self):
        result = decode([request(1, 10), request(2, 12, opcode=0)], [returned(1, 20)])
        self.assertEqual(result['status'], 'invalid')
        self.assertTrue(any('reused' in e['reason'] for e in result['errors']))

    def test_unpaired_and_malformed_payload_rejected(self):
        self.assertEqual(decode([], [returned(1, 20)])['status'], 'invalid')
        for row in [returned(1, 20, payload='00'), returned(1, 20, source=64)]:
            with self.assertRaises(RuntimeError):
                decode([request(1, 10)], [row])

    def test_backpressure_does_not_double_count_payload(self):
        result = decode([request(1, 10)], [returned(1, 18, ready=0),
                        returned(2, 19, ready=0), returned(3, 20)])
        self.assertEqual(result['metrics']['read_payload_bytes'], 64)
        self.assertEqual(result['metrics']['read_return_backpressure_cycles'], 2)
        self.assertEqual(result['metrics']['read_completion_latency'], 10)

    def test_legacy_capture_does_not_gain_read_metrics(self):
        result = memory.decode([request(1, 10)])
        self.assertIsNone(result['metrics']['read_payload_bytes'])
        self.assertIsNone(result['boundary']['read_inflight'])


if __name__ == '__main__':
    unittest.main()

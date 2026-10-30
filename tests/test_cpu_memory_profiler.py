import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import kda_cpu_memory as cpu


def load(kind=0,epoch=100,stamp=1000,mask=15,flags=194,meta=1,pipe=0,sn=12,pc=0x80001000,miss=0,replay=0):
    return (1+kind,kind,epoch,stamp,pipe,meta,mask,0x80002000,pc,0x3,sn,0,flags,0,0,0x80002000 if kind else 0,miss,replay,0)


class CpuMemoryTests(unittest.TestCase):
    def test_actual_mask_and_local_status(self):
        value=cpu.decode([load(),load(1,102,1002)],begin=999,end=1001)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['metrics']['scalar_read_request_enabled_bytes'],4)
        self.assertEqual(value['requests'][0]['status_latency_cycles'],2)
        self.assertTrue(value['requests'][0]['metadata_agreement'])
        self.assertEqual(value['boundary']['leaving_statuses'],1)
        self.assertIsNone(value['metrics']['read_payload_bytes'])

    def test_replay_is_real_attempt_not_deduplicated(self):
        rows=[load(),load(1,102,1002,miss=1,replay=1),load(epoch=103,stamp=1003,flags=146),load(1,105,1005,flags=146)]
        value=cpu.decode(rows)
        self.assertEqual(value['metrics']['demand_read_request_enabled_bytes'],8)
        self.assertEqual(value['metrics']['replay_read_requests'],1)
        self.assertEqual(value['metrics']['l1_status_replays'],1)

    def test_missing_metadata_does_not_fabricate_bytes(self):
        value=cpu.decode([load(meta=0)])
        self.assertEqual(value['metrics']['load_requests_unknown_metadata'],1)
        self.assertEqual(value['metrics']['demand_read_request_enabled_bytes'],0)
        self.assertIsNone(value['requests'][0]['mask'])

    def test_metadata_disagreement_blocks_source(self):
        value=cpu.decode([load(),load(1,102,1002,sn=99)])
        self.assertEqual(value['metrics']['response_metadata_disagreements'],1)
        self.assertEqual(value['requests'][0]['ownership'],'unverified_response_metadata')

    def test_rvv_unique_sn_recovers_source_and_preserves_raw_pc(self):
        rows=[load(flags=195,pc=4),load(1,102,1002,flags=195,pc=4)]
        value=cpu.decode(rows,pcmap={0x80001000:{'function':'vload'}},
                         committed={12:{'pc':0x80001000,'stamp':1010}})
        event=value['requests'][0]
        self.assertEqual(event['pc'],'0x80001000')
        self.assertEqual(event['raw_rtl_pc'],'0x4')
        self.assertEqual(event['source']['function'],'vload')
        self.assertTrue(event['metadata_agreement'])
        unknown=cpu.decode([load(flags=195,pc=4,sn=0)])
        self.assertIsNone(unknown['requests'][0]['pc'])
        self.assertIsNone(unknown['requests'][0]['source'])

    def test_clock_discontinuity_is_invalid(self):
        value=cpu.decode([load(),load(1,102,1003)])
        self.assertEqual(value['status'],'invalid')

    def test_unpaired_response_is_invalid(self):
        self.assertEqual(cpu.decode([load(1,102,1002)])['status'],'invalid')

    def test_store_boundaries_not_added(self):
        value=cpu.decode([],[(1,1000,0x80000000,15,0,0,1,0,0x80001000,2,0,0),
                             (2,1001,0x80000000,65535,1,0,1,0,0x80001000,2,0,1)],
                         [(1,1002,0x80000000,-1,0,0)])
        self.assertEqual(value['metrics']['pma_store_known_enabled_bytes'],4)
        self.assertEqual(value['metrics']['pma_store_unknown_bytes_events'],1)
        self.assertEqual(value['metrics']['sbuffer_completion_enabled_bytes'],64)
        self.assertIsNone(value['metrics']['total_cpu_rvv_memory_bytes'])

    def test_vector_prefetch_and_speculation(self):
        value=cpu.decode([load(flags=195),load(epoch=101,stamp=1001,flags=198)])
        self.assertEqual(value['metrics']['rvv_read_request_enabled_bytes'],4)
        self.assertEqual(value['metrics']['prefetch_requests'],1)
        self.assertEqual(value['requests'][0]['ownership'],'not_in_selected_retirement_records')

if __name__=='__main__': unittest.main()

"""Reviewed ordinary LSU/L1 events. Requests, status responses and stores are separate."""
from collections import Counter
import sqlite3

import kda_profile as p

FLAGS = ('is_vector', 'vector_active', 'prefetch', 'hardware_prefetch', 'load_replay',
         'fast_replay', 'first_issue', 'has_rob_entry', 'misaligned', 'from_misalign_buffer', 'final_split')
COLUMNS = 'ID,KIND,EPOCH,CPU_STAMP,PIPE,META,MASK,VADDR,PC,CODE,SN,UOP,FLAGS,ELEM,OFFSET,PADDR,MISS,REPLAY,KILLED'
LIMITATIONS = [
    'Read bytes are enabled lanes on actual ordinary LoadUnit-to-L1 request handshakes, including replay and speculative attempts; they are not unique data, cacheline fills or DRAM bytes.',
    'Only requests with same-edge accepted S1 metadata have known byte masks. Missing metadata remains unknown and is counted explicitly.',
    'L1 responses are status responses (hit/miss/replay), not observed read payload or architectural load completion. Their latency is local request-to-status latency only.',
    'Request/response pairing uses the reviewed fixed two-edge pipeline and exact port; metadata disagreement blocks instruction attribution.',
    'PMA store events report enabled lanes after store acceptance, delayed two RTL edges. Store-buffer completion masks reflect merging and are reported separately, never added to PMA bytes.',
    'Whole-line stores have special semantics and remain unknown bytes. Atomics, vector-segment and uncached/MMIO paths are outside this ordinary-load/PMA-store coverage.',
    'RVV flow PCs are unavailable in this model. Only unique nonzero dynamic SNs that match this DB retirement can recover source; all missing SNs stay unattributed.',
    'Timestamp overlap selects the requested call/stage. Speculation, replay, split flows and boundary crossings are retained; overlap alone does not prove retired instruction ownership.',
]


def decode(loads, stores=(), sbuffer=(), begin=None, end=None, pcmap=None, committed=None):
    p.require((begin is None) == (end is None) and (begin is None or 0 <= begin < end), 'Invalid CPU memory interval')
    pcmap, committed = pcmap or {}, committed or {}
    def selected(stamp):
        return begin is None or begin <= stamp < end
    errors, requests, responses, pending = [], [], [], {}
    clock_offsets, raw = Counter(), Counter()
    for row in sorted(loads, key=lambda row: (row[2], row[1] == 0, row[0])):
        p.require(len(row) == 19 and all(type(v) is int and v >= 0 for v in row), 'Invalid CPU load event types')
        ident, kind, epoch, stamp, pipe, meta, mask, va, pc, code, sn, uop, bits, elem, offset, pa, miss, replay, killed = row
        p.require(kind in (0, 1) and pipe in range(3) and mask < 65536 and bits < 2048,
                  'Unreviewed CPU load event kind, port, mask or flags')
        p.require(all(v in (0, 1) for v in (meta, miss, replay, killed)), 'Invalid CPU load status bits')
        clock_offsets[stamp-epoch] += 1
        flags = {name: bool(bits & (1 << i)) for i, name in enumerate(FLAGS)}
        event = dict(id=ident, epoch=epoch, cpu_stamp=stamp, pipe=pipe, metadata_valid=bool(meta),
                     mask=hex(mask) if meta else None, enabled_bytes=mask.bit_count() if meta else None,
                     virtual_address=hex(va) if meta else None, pc=hex(pc) if meta else None, raw_rtl_pc=hex(pc) if meta else None,
                     instruction_code=None, raw_rtl_instruction_field=code if meta else None, sn=sn if meta else None, uop=uop if meta else None,
                     flags=flags if meta else None, element_index=elem if meta else None,
                     register_offset=offset if meta else None)
        if kind == 0:
            key = (pipe, epoch)
            p.require(key not in pending, 'Duplicate CPU request on one pipe/edge')
            event.update(kind='read_request', response_cpu_stamp=None, status_latency_cycles=None,
                         response_epoch=None, response=None, metadata_agreement=None,
                         physical_address=None, completion='no_observed_status', source=None,
                         ownership='unknown')
            if meta:
                retired = committed.get(sn) if sn else None
                mapped_pc = pc
                if flags['is_vector'] and pc < 0x80000000:
                    # This generated VecPipe has no usable PC; retain raw PC and
                    # accept only a unique nonzero SN present in this DB's retirement.
                    event['raw_rtl_pc'] = event['pc']
                    event['pc'] = hex(retired['pc']) if retired else None
                    mapped_pc = retired['pc'] if retired else None
                    event['ownership'] = 'retired_instruction_unique_sn_rvv_pc_unavailable' if retired else 'unattributed_rvv_flow_missing_sn_or_retirement'
                elif retired and retired['pc'] == pc:
                    event['ownership'] = 'retired_instruction_same_sn_pc'
                else:
                    event['ownership'] = 'not_in_selected_retirement_records'
                detail = pcmap.get(mapped_pc)
                if detail:
                    event['source'] = {key: detail.get(key) for key in
                                       ('function', 'source', 'instruction', 'archived_source', 'disassembly_context')}
                if retired:
                    event['commit_cpu_stamp'] = retired['stamp']
            pending[key] = event
            requests.append(event)
        else:
            event.update(kind='l1_status', physical_address=hex(pa), miss=bool(miss), replay=bool(replay), killed=bool(killed))
            response_key = (pipe, epoch-2)
            tx = pending.get(response_key)
            if tx is None:
                errors.append({'event': ident, 'reason': 'L1 status lacks observed same-pipe request two edges earlier'})
            elif tx['response'] is not None:
                errors.append({'event': ident, 'reason': 'Duplicate L1 status for a request'})
            else:
                agree = bool(meta and tx['metadata_valid'] and
                             (sn, uop, mask, va, pc) == (tx['sn'], tx['uop'], int(tx['mask'], 16), int(tx['virtual_address'], 16), int(tx['raw_rtl_pc'],16)))
                tx.update(response_cpu_stamp=stamp, response_epoch=epoch,
                          status_latency_cycles=stamp-tx['cpu_stamp'], response=event,
                          metadata_agreement=agree, physical_address=hex(pa), completion='observed_l1_status')
                if not agree:
                    tx['ownership'] = 'unverified_response_metadata'
                    tx['source'] = None
            responses.append(event)
    chosen = [e for e in requests if selected(e['cpu_stamp'])]
    demand = [e for e in chosen if e['metadata_valid'] and not e['flags']['prefetch'] and
              e['flags']['has_rob_entry'] and (not e['flags']['is_vector'] or e['flags']['vector_active'])]
    scalar = [e for e in demand if not e['flags']['is_vector']]
    vector = [e for e in demand if e['flags']['is_vector']]
    hist = Counter(e['status_latency_cycles'] for e in chosen if e['status_latency_cycles'] is not None)
    store_events = []
    for row in stores:
        p.require(len(row) == 12 and all(type(v) is int and v >= 0 for v in row), 'Invalid CPU store event')
        ident, stamp, addr, mask, wline, split, eew, offset, pc, rob, core, port = row
        p.require(core == 0 and mask < 65536 and wline in (0, 1) and split in (0, 1), 'Unreviewed PMA store event')
        if not selected(stamp):
            continue
        detail = pcmap.get(pc)
        store_events.append(dict(id=ident, kind='pma_store', cpu_stamp=stamp, address=hex(addr), mask=hex(mask),
                                 enabled_bytes=None if wline else mask.bit_count(), whole_line=bool(wline),
                                 vector_line=bool(split), element_bytes=eew, offset=offset, pc=hex(pc),
                                 rob_index=rob, port=port,
                                 source={key: detail.get(key) for key in ('function', 'source', 'instruction', 'archived_source', 'disassembly_context')} if detail else None,
                                 originating_fire_stamp=None, timestamp_delay_edges=2))
    completed = []
    for row in sbuffer:
        p.require(len(row) == 6 and all(type(v) is int and v >= 0 for i,v in enumerate(row) if i != 3), 'Invalid store-buffer completion')
        ident, stamp, addr, mask, core, port = row
        p.require(type(mask) is int and core == 0, 'Invalid store-buffer mask/core')
        if selected(stamp):
            completed.append(dict(id=ident, kind='sbuffer_completion', cpu_stamp=stamp, address=hex(addr),
                                  mask=hex(mask & ((1 << 64)-1)), enabled_bytes=(mask & ((1 << 64)-1)).bit_count(),
                                  port=port, timestamp_delay_edges=1))
    functions = {}
    for e in [*demand, *store_events]:
        function = (e.get('source') or {}).get('function', 'unattributed')
        item = functions.setdefault(function, dict(function=function, read_requests=0, read_request_enabled_bytes=0,
                                                  pma_store_events=0, pma_store_enabled_bytes=0, unknown_store_bytes_events=0))
        if e['kind'] == 'read_request':
            item['read_requests'] += 1
            item['read_request_enabled_bytes'] += e['enabled_bytes']
        else:
            item['pma_store_events'] += 1
            item['pma_store_enabled_bytes'] += e['enabled_bytes'] or 0
            item['unknown_store_bytes_events'] += e['enabled_bytes'] is None
    if len(clock_offsets) > 1:
        errors.append({'reason': 'Observed CPU stamp/EPOCH offset changes'})
    metrics = dict(load_request_attempts=len(chosen), demand_read_requests=len(demand),
                   demand_read_request_enabled_bytes=sum(e['enabled_bytes'] for e in demand),
                   scalar_read_request_enabled_bytes=sum(e['enabled_bytes'] for e in scalar),
                   rvv_read_request_enabled_bytes=sum(e['enabled_bytes'] for e in vector),
                   load_requests_unknown_metadata=sum(not e['metadata_valid'] for e in chosen),
                   read_requests_source_unattributed=sum(e['source'] is None for e in demand),
                   read_request_bytes_source_unattributed=sum(e['enabled_bytes'] for e in demand if e['source'] is None),
                   prefetch_requests=sum(bool(e['metadata_valid'] and e['flags']['prefetch']) for e in chosen),
                   replay_read_requests=sum(e['flags']['load_replay'] or e['flags']['fast_replay'] for e in demand),
                   split_or_misaligned_read_requests=sum(e['flags']['misaligned'] or e['flags']['from_misalign_buffer'] for e in demand),
                   observed_l1_statuses=sum(e['response'] is not None for e in chosen),
                   l1_status_misses=sum(bool(e['response'] and e['response']['miss']) for e in chosen),
                   l1_status_replays=sum(bool(e['response'] and e['response']['replay']) for e in chosen),
                   response_metadata_disagreements=sum(e['metadata_agreement'] is False for e in chosen),
                   pma_store_events=len(store_events), pma_store_known_enabled_bytes=sum(e['enabled_bytes'] or 0 for e in store_events),
                   pma_store_unknown_bytes_events=sum(e['enabled_bytes'] is None for e in store_events),
                   sbuffer_completions=len(completed), sbuffer_completion_enabled_bytes=sum(e['enabled_bytes'] for e in completed),
                   read_payload_bytes=None, architectural_load_latency=None, total_cpu_rvv_memory_bytes=None, dram_bytes=None)
    return dict(schema='xsai-prof.cpu-memory/v1', status='invalid' if errors else 'available', errors=errors,
                coverage='ordinary scalar/RVV LoadUnit requests and PMA store events; partial CPU memory coverage',
                scope=dict(begin_cpu_stamp=begin, end_cpu_stamp_exclusive=end, policy='event initiation timestamp overlap; status responses followed beyond end'),
                timestamps=dict(domain='PerfCCT.global_tick_acc sampled before rising edge for loads; callback stamp for stores',
                                epoch_offset_histogram=dict(clock_offsets), status_latency_histogram=dict(hist)),
                metrics=metrics, boundary=dict(
                    leaving_statuses=sum(e['response_cpu_stamp'] is not None and end is not None and e['response_cpu_stamp'] >= end for e in chosen),
                    entering_statuses=sum(e['cpu_stamp'] < begin and e['response_cpu_stamp'] is not None and selected(e['response_cpu_stamp']) for e in requests) if begin is not None else 0,
                    no_observed_status=sum(e['response'] is None for e in chosen)),
                functions=sorted(functions.values(), key=lambda r: r['read_request_enabled_bytes']+r['pma_store_enabled_bytes'], reverse=True),
                requests=chosen, store_events=store_events, sbuffer_events=completed, limitations=LIMITATIONS)


def from_connection(connection, interval, trace):
    names={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {'XSAICpuLoad', 'XSAICpuStore', 'XSAISbuffer'} <= names:
        return dict(status='unavailable', reason='No reviewed CPU memory capture tables', metrics=None)
    pcmap={int(item['pc'],16): item for item in trace.get('pcs', [])}
    committed={sn: dict(pc=pc,stamp=stamp) for sn,pc,stamp in connection.execute(
        'SELECT SN,MIN(PC),MAX(AtCommit) FROM LifeTimeCommitTrace WHERE AtCommit>0 GROUP BY SN HAVING COUNT(DISTINCT PC)=1')}
    return decode(connection.execute('SELECT '+COLUMNS+' FROM XSAICpuLoad').fetchall(),
                  connection.execute('SELECT * FROM XSAICpuStore').fetchall(),
                  connection.execute('SELECT * FROM XSAISbuffer').fetchall(), *interval, pcmap, committed)

"""Readable observations and falsifiable next experiments from verified analysis."""


def overview(analysis):
    performance = analysis['performance']
    memory = analysis['memory']
    observations = list(analysis['diagnosis']['observations'])
    hypotheses = []
    if memory.get('status') == 'available':
        metrics = memory['metrics']
        observations.append({'kind': 'ame_memory', 'evidence': '/memory/metrics',
            'values': {key: metrics.get(key) for key in ('read_requested_bytes', 'read_payload_bytes',
                'read_completion_latency', 'read_outstanding_max', 'write_payload_bytes')},
            'interpretation': 'Actual reviewed AME interface traffic. Null means unobserved; service latency includes queueing and backpressure.'})
        if metrics.get('observed_read_completions', 0) > 0:
            hypotheses.append({'id': 'ame_read_overlap', 'status': 'untested',
                'statement': 'Changing independent tile scheduling may change AME read overlap and service time.',
                'evidence': ['/memory/metrics/read_completion_latency', '/memory/metrics/read_outstanding_max'],
                'experiment': 'Keep shape, numerical contract and hardware fixed; change one scheduling choice, pass correctness, then collect fresh independent perf and paired read-return diagnostics.',
                'prediction': 'If read overlap limits this workload, the proposed schedule changes the predicted outstanding/latency distribution and lowers independent perf cycles.',
                'falsifier': 'Cycles do not improve, or predicted read events do not change; reject the proposed mechanism.',
                'missing_evidence': ['Schedule ablation and repeated independent performance.']})
        cpu = memory.get('cpu', {})
        if cpu.get('status') == 'available':
            observations.append({'kind': 'cpu_rvv_memory', 'evidence': '/memory/cpu/metrics',
                'values': {key: cpu['metrics'].get(key) for key in ('rvv_read_request_enabled_bytes',
                    'pma_store_known_enabled_bytes', 'load_requests_unknown_metadata')},
                'interpretation': 'Partial LSU request attempts and PMA stores; requests include replay/speculation. This does not measure full CPU or DRAM traffic.'})
    comparison = analysis.get('comparison')
    changes = []
    if comparison:
        comparison_memory = comparison.get('sections', {}).get('trace', {}).get('memory', {})
        for boundary, rows in [('ame', comparison_memory.get('metrics', [])),
                               ('cpu_rvv', comparison_memory.get('cpu', {}).get('metrics', []))]:
            for row in rows:
                if row.get('delta') not in (None, 0):
                    changes.append({'boundary': boundary, **row,
                        'evidence': '/comparison/sections/trace/memory'})
    return {'schema': 'xsai-prof.overview/v1',
        'performance': {'repeat_count': performance.get('repeat_count'),
            'measurements': performance.get('measurements', []),
            'semantics': 'Independent uninstrumented RTL cycles; diagnostic intervals do not establish speedup.'},
        'observations': observations, 'memory_changes': changes, 'hypotheses': hypotheses,
        'coverage': {'trace': analysis.get('trace_status', 'unavailable'), 'memory': memory.get('status'),
            'ame_read_returns': memory.get('read_returns', {}).get('status', 'unavailable'),
            'cpu_rvv_memory': memory.get('cpu', {}).get('status', 'unavailable'),
            'dram_bytes': 'unavailable', 'architectural_load_latency': 'unavailable'},
        'limits': list(dict.fromkeys(analysis.get('warnings', []) + memory.get('limitations', []) + [
            'Source hotspots use retirement-gap attribution, not exclusive function time.',
            'Observed changes support an experiment; they do not establish a causal bottleneck.']))}

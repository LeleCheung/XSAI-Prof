"""Exact reviewed observation build, not a contract for arbitrary emulator names."""
OBSERVER = {
    'emulator_sha256': '79cf1e730fcbb2ba01f3fd0fa833103eab5574a7cf9122c3f6af3fd2730c93c1',
    'logger_sha256': '2b859d10de395ec59e2315143bcdbd2d2e98801506a43d5962c0b3ed1d265d95',
    'lifetime_sha256': 'ccf7bf61baf835f908889bfb9a1475fb05c6d8cf10be89c682b08ff34dc641a4',
    'header_sha256': 'ad0dcc043714748634329fe4a43aed8d73e4e0190f1ae40a524f0647ae079f84',
    'base_emulator_sha256': '189681b2f3aa6fe9f51891acd9df0bb51b250305ecd970f2d0b26a619541adfd',
}


def _legacy_reviewed(receipt):
    if not isinstance(receipt, dict):
        return False
    memory, bridge = receipt.get('memory_observer', {}), receipt.get('clock_bridge', {})
    return (receipt.get('emulator', {}).get('sha256') == OBSERVER['emulator_sha256'] and
            receipt.get('configuration', {}).get('NUM_CORES') == '1' and
            bridge.get('observer_sha256') == OBSERVER['logger_sha256'] and
            bridge.get('base_emulator_sha256') == OBSERVER['base_emulator_sha256'] and
            bridge.get('single_core_only') is True and memory.get('schema') == 'xsai-prof.observer/v1' and
            memory.get('chisel_db.cpp') == OBSERVER['logger_sha256'] and
            memory.get('perfCCT.cpp') == OBSERVER['lifetime_sha256'] and
            memory.get('observer.h') == OBSERVER['header_sha256'] and
            memory.get('beat_bytes') == 64 and memory.get('rtl_regenerated') is False)


def _cpu_reviewed(receipt, expected):
    """Exact experimental CPU observer identity; no arbitrary model is trusted."""
    if not isinstance(receipt, dict):
        return False
    memory, bridge = receipt.get('memory_observer', {}), receipt.get('clock_bridge', {})
    cpu = memory.get('cpu_observer', {})
    return (receipt.get('emulator', {}).get('sha256') == expected['emulator_sha256'] and
            receipt.get('configuration', {}).get('NUM_CORES') == '1' and
            bridge.get('base_emulator_sha256') == OBSERVER['base_emulator_sha256'] and
            bridge.get('single_core_only') is True and
            bridge.get('observer_sha256') == expected['sources']['chisel_db.cpp'] and
            memory.get('schema') == 'xsai-prof.observer/v1' and
            all(memory.get(k) == expected['sources'][k] for k in ('chisel_db.cpp', 'perfCCT.cpp', 'observer.h')) and
            memory.get('beat_bytes') == 64 and memory.get('rtl_regenerated') is False and
            cpu.get('schema') == 'xsai-prof.cpu-memory/v1' and
            cpu.get('sources') == expected['sources'] and
            cpu.get('signal_review_sha256') == expected['signal_review_sha256'] and
            cpu.get('load_pipelines') == 3 and cpu.get('load_beat_bytes') == 16 and
            cpu.get('rtl_regenerated') is False)


def cpu_reviewed(receipt):
    return _cpu_reviewed(receipt, CPU_OBSERVER) or ame_read_reviewed(receipt)


def ame_read_reviewed(receipt):
    if not isinstance(receipt, dict) or not _cpu_reviewed(receipt, AME_READ_OBSERVER):
        return False
    read = receipt.get('memory_observer', {}).get('ame_read_observer', {})
    return (read.get('schema') == 'xsai-prof.ame-read/v1' and
            read.get('sources') == AME_READ_OBSERVER['sources'] and
            read.get('signal_review_sha256') == AME_READ_OBSERVER['ame_signal_review_sha256'] and
            read.get('table') == 'XSAIAMERead' and read.get('beat_bytes') == 64 and
            read.get('rtl_regenerated') is False)


def reviewed(receipt):
    return _legacy_reviewed(receipt) or cpu_reviewed(receipt)

CPU_OBSERVER = {'emulator_sha256': '09c4cdd69f09bb6955e1c455b3a9916d916e4a8aaab63dbae6f99211db3e70d8', 'sources': {'chisel_db.cpp': '38df3e3e270c87a0e28aa9f6fb8b062bd0cec10f97e5e7f92e88dc601762c5a3', 'chisel_db.h': '2fb4299d97cc51f30ecf7b7fb70914e4a89f885a8f340e082dbfd9e7dcd9d06c', 'perfCCT.cpp': 'ccf7bf61baf835f908889bfb9a1475fb05c6d8cf10be89c682b08ff34dc641a4', 'cpu_observer.h': 'f69150bce99c784d6632f95777206ae9119f4e3802c156303d2e766486f402d4', 'perfCCT.h': 'be4692ce0e24602fb04a228b495fc30033c17417c5f9fe8ea745be6a7df7dd70', 'verilator.h': '879deca136ea85e00dd352f5ec6efc8cdb2db00b6ac2c9715b721f20c9cb9728', 'cpu_sampler.cpp': 'f5bb0af5029eab2eda5aae085db40d1c57efe74c89c04cd4bf41a98d623ee1e9', 'observer.h': 'ad0dcc043714748634329fe4a43aed8d73e4e0190f1ae40a524f0647ae079f84', 'difftest-dpic.h': 'ef2279435fc2e9f07e939892d722ed41aeb953f9bd794ec112f2fcf2b47870a0', 'difftest-dpic.cpp': 'cb9a16be5a8ed1b14e33ea7636f13b52686309aedda01a2a58f31f9d628679a8', 'emu.cpp': '42b38a87ba63f02da3235009275c24e321ae554500275982d15f03f4353e6fbd', 'emu.h': '02dd7b3b3640785e688708d8da1871fcee5f0282fcd9e37047a1375e264c349e', 'simulator.h': '2b2171cb5c9856522c7148c65bcedc44e4d4bc8754324307b17491aeb019681c', 'verilator.cpp': '27f050bcdd31b3d62a4c9bb17e4286e881963a887546249dbe903ced4d3751da'}, 'signal_review_sha256': '591643d068ccbfe754bec0309c718dbd7cb5c123b2f9d708000fb2741fdc0852'}


AME_READ_OBSERVER = {'emulator_sha256': '18aa71d488e08977b288b58a4173c8f8f611478ae012d788d3e7f0249c1af426', 'sources': {'chisel_db.cpp': '3af5457469c37920a3fa15a625a56d65e7494eac6fce406e1d34df9da3cec42f', 'chisel_db.h': '2fb4299d97cc51f30ecf7b7fb70914e4a89f885a8f340e082dbfd9e7dcd9d06c', 'perfCCT.cpp': 'ccf7bf61baf835f908889bfb9a1475fb05c6d8cf10be89c682b08ff34dc641a4', 'cpu_observer.h': 'f69150bce99c784d6632f95777206ae9119f4e3802c156303d2e766486f402d4', 'perfCCT.h': 'be4692ce0e24602fb04a228b495fc30033c17417c5f9fe8ea745be6a7df7dd70', 'verilator.h': '879deca136ea85e00dd352f5ec6efc8cdb2db00b6ac2c9715b721f20c9cb9728', 'cpu_sampler.cpp': '0c006ba44fa6392f0bd5e6a6bd260087517d93434a3b54990276a1b32268d599', 'observer.h': 'ad0dcc043714748634329fe4a43aed8d73e4e0190f1ae40a524f0647ae079f84', 'difftest-dpic.h': 'ef2279435fc2e9f07e939892d722ed41aeb953f9bd794ec112f2fcf2b47870a0', 'difftest-dpic.cpp': 'cb9a16be5a8ed1b14e33ea7636f13b52686309aedda01a2a58f31f9d628679a8', 'emu.cpp': '42b38a87ba63f02da3235009275c24e321ae554500275982d15f03f4353e6fbd', 'emu.h': '02dd7b3b3640785e688708d8da1871fcee5f0282fcd9e37047a1375e264c349e', 'simulator.h': '2b2171cb5c9856522c7148c65bcedc44e4d4bc8754324307b17491aeb019681c', 'verilator.cpp': '27f050bcdd31b3d62a4c9bb17e4286e881963a887546249dbe903ced4d3751da'}, 'signal_review_sha256': '591643d068ccbfe754bec0309c718dbd7cb5c123b2f9d708000fb2741fdc0852', 'ame_signal_review_sha256': 'a13e215fc5e8c16981689b2a36e1e004fc9b15e629d018463a8922a0708cf8fc'}

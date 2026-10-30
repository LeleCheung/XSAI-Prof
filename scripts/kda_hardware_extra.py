"""Additional reviewed predicates; upstream excerpts under Mulan PSL v2.
See bundled RTL license and notice.
"""
SOURCES = {'ifu_new': {'file': 'src/main/scala/xiangshan/frontend/IFU.scala',
             'sha256': '7b7dce57088f2a44c2da6b768a2ca2dadc729c7c8232e5001df8e64c49672577',
             'lines': [{'number': 1191, 'text': '  val f3_req_1     = io.toIbuffer.fire && f3_doubleLine'},
                       {'number': 1192,
                        'text': '  val f3_hit_0     = io.toIbuffer.fire && f3_perf_info.bank_hit(0)'},
                       {'number': 1193,
                        'text': '  val f3_hit_1     = io.toIbuffer.fire && f3_doubleLine & '
                                'f3_perf_info.bank_hit(1)'},
                       {'number': 1194, 'text': '  val f3_hit       = f3_perf_info.hit'},
                       {'number': 1195, 'text': '  val perfEvents = Seq('},
                       {'number': 1196, 'text': '    ("frontendFlush                ", wb_redirect),'},
                       {'number': 1197, 'text': '    ("ifu_req                      ", io.toIbuffer.fire),'},
                       {'number': 1198,
                        'text': '    ("ifu_miss                     ", io.toIbuffer.fire && '
                                '!f3_perf_info.hit),'},
                       {'number': 1199, 'text': '    ("ifu_req_cacheline_0          ", f3_req_0),'},
                       {'number': 1200, 'text': '    ("ifu_req_cacheline_1          ", f3_req_1),'},
                       {'number': 1201, 'text': '    ("ifu_req_cacheline_0_hit      ", f3_hit_1),'},
                       {'number': 1202, 'text': '    ("ifu_req_cacheline_1_hit      ", f3_hit_1),'},
                       {'number': 1203,
                        'text': '    ("only_0_hit                   ", f3_perf_info.only_0_hit && '
                                'io.toIbuffer.fire),'},
                       {'number': 1204,
                        'text': '    ("only_0_miss                  ", f3_perf_info.only_0_miss && '
                                'io.toIbuffer.fire),'},
                       {'number': 1205,
                        'text': '    ("hit_0_hit_1                  ", f3_perf_info.hit_0_hit_1 && '
                                'io.toIbuffer.fire),'},
                       {'number': 1206,
                        'text': '    ("hit_0_miss_1                 ", f3_perf_info.hit_0_miss_1 && '
                                'io.toIbuffer.fire),'},
                       {'number': 1207,
                        'text': '    ("miss_0_hit_1                 ", f3_perf_info.miss_0_hit_1 && '
                                'io.toIbuffer.fire),'},
                       {'number': 1208,
                        'text': '    ("miss_0_miss_1                ", f3_perf_info.miss_0_miss_1 && '
                                'io.toIbuffer.fire)'},
                       {'number': 1209, 'text': '  )'},
                       {'number': 1210, 'text': '  generatePerfEvent()'}]},
 'ftq_redirect': {'file': 'src/main/scala/xiangshan/frontend/NewFtq.scala',
                  'sha256': 'ab5bf70b5e6c47ac2a2b5fea8c9652a9265f4631b16da9ddadee4f3e77736815',
                  'lines': [{'number': 1498,
                             'text': '  // '
                                     '******************************************************************************'},
                            {'number': 1499, 'text': ''},
                            {'number': 1500,
                             'text': '  val commit_inst_mask        = VecInit(commit_state.map(c => c === '
                                     'c_committed && do_commit)).asUInt'},
                            {'number': 1501,
                             'text': '  val commit_mispred_mask     = commit_mispredict.asUInt'},
                            {'number': 1502, 'text': '  val commit_not_mispred_mask = ~commit_mispred_mask'},
                            {'number': 1503, 'text': ''},
                            {'number': 1504, 'text': '  val commit_br_mask  = commit_pd.brMask.asUInt'},
                            {'number': 1505,
                             'text': '  val commit_jmp_mask = UIntToOH(commit_pd.jmpOffset) & '
                                     'Fill(PredictWidth, commit_pd.jmpInfo.valid.asTypeOf(UInt(1.W)))'},
                            {'number': 1506,
                             'text': '  val commit_cfi_mask = commit_br_mask | commit_jmp_mask'},
                            {'number': 1507, 'text': ''},
                            {'number': 1508, 'text': '  val mbpInstrs = commit_inst_mask & commit_cfi_mask'},
                            {'number': 1509, 'text': ''},
                            {'number': 1510, 'text': '  val mbpRights = mbpInstrs & commit_not_mispred_mask'},
                            {'number': 1511, 'text': '  val mbpWrongs = mbpInstrs & commit_mispred_mask'},
                            {'number': 1570, 'text': '  val perf_redirect = backendRedirect'},
                            {'number': 1571, 'text': ''},
                            {'number': 1572, 'text': '  XSPerfAccumulate("entry", validEntries)'},
                            {'number': 1573,
                             'text': '  XSPerfAccumulate("bpu_to_ftq_stall", enq.valid && !enq.ready)'},
                            {'number': 1574,
                             'text': '  XSPerfAccumulate("mispredictRedirect", perf_redirect.valid && '
                                     'RedirectLevel.flushAfter === perf_redirect.bits.level)'},
                            {'number': 1575,
                             'text': '  XSPerfAccumulate("replayRedirect", perf_redirect.valid && '
                                     'RedirectLevel.flushItself(perf_redirect.bits.level))'},
                            {'number': 1576,
                             'text': '  XSPerfAccumulate("predecodeRedirect", fromIfuRedirect.valid)'},
                            {'number': 1577, 'text': ''},
                            {'number': 1578,
                             'text': '  XSPerfAccumulate("to_ifu_bubble", io.toIfu.req.ready && '
                                     '!io.toIfu.req.valid)'},
                            {'number': 1769, 'text': '  val perfEvents = Seq('},
                            {'number': 1770, 'text': '    ("bpu_s2_redirect        ", bpu_s2_redirect),'},
                            {'number': 1771, 'text': '    ("bpu_s3_redirect        ", bpu_s3_redirect),'},
                            {'number': 1772,
                             'text': '    ("bpu_to_ftq_stall       ", enq.valid && ~enq.ready),'},
                            {'number': 1773,
                             'text': '    ("mispredictRedirect     ", perf_redirect.valid && '
                                     'RedirectLevel.flushAfter === perf_redirect.bits.level),'},
                            {'number': 1774,
                             'text': '    ("replayRedirect         ", perf_redirect.valid && '
                                     'RedirectLevel.flushItself(perf_redirect.bits.level)),'},
                            {'number': 1775,
                             'text': '    ("predecodeRedirect      ", fromIfuRedirect.valid),'},
                            {'number': 1776,
                             'text': '    ("to_ifu_bubble          ", io.toIfu.req.ready && '
                                     '!io.toIfu.req.valid),'},
                            {'number': 1777,
                             'text': '    ("from_bpu_real_bubble   ", !enq.valid && enq.ready && '
                                     'allowBpuIn),'},
                            {'number': 1778, 'text': '    ("BpInstr                ", PopCount(mbpInstrs)),'},
                            {'number': 1779,
                             'text': '    ("BpBInstr               ", PopCount(mbpBRights | mbpBWrongs)),'},
                            {'number': 1780,
                             'text': '    ("BpRight                ", PopCount(mbpRights)),'}]},
 'ibuffer_full': {'file': 'src/main/scala/xiangshan/frontend/IBuffer.scala',
                  'sha256': 'f6fddab79e5389950c0414d60d10cad2c1f6679ac05a7554ce2f5855dde48974',
                  'lines': [{'number': 218, 'text': ''},
                            {'number': 219, 'text': '  // counter current number of valid'},
                            {'number': 220,
                             'text': '  val numValid         = distanceBetween(enqPtr, deqPtr)'},
                            {'number': 221, 'text': '  val numValidAfterDeq = numValid - numDeq'},
                            {'number': 222, 'text': '  // counter next number of valid'},
                            {'number': 223, 'text': '  val numValidNext = numValid + numEnq - numDeq'},
                            {'number': 224, 'text': '  val allowEnq     = RegInit(true.B)'},
                            {'number': 225,
                             'text': '  val numFromFetch = Mux(io.in.valid, PopCount(io.in.bits.enqEnable), '
                                     '0.U)'},
                            {'number': 226, 'text': ''},
                            {'number': 227,
                             'text': '  allowEnq := (IBufSize - PredictWidth).U >= numValidNext // Disable '
                                     'when almost full'},
                            {'number': 228, 'text': ''},
                            {'number': 229,
                             'text': '  val enqOffset = VecInit.tabulate(PredictWidth)(i => '
                                     'PopCount(io.in.bits.valid.asBools.take(i)))'},
                            {'number': 490, 'text': '  val perfEvents = Seq('},
                            {'number': 491, 'text': '    ("IBuffer_Flushed  ", io.flush),'},
                            {'number': 492, 'text': '    ("IBuffer_hungry   ", instrHungry),'},
                            {'number': 493,
                             'text': '    ("IBuffer_1_4_valid", (numValid > (0 * (IBufSize / 4)).U) & '
                                     '(numValid < (1 * (IBufSize / 4)).U)),'},
                            {'number': 494,
                             'text': '    ("IBuffer_2_4_valid", (numValid >= (1 * (IBufSize / 4)).U) & '
                                     '(numValid < (2 * (IBufSize / 4)).U)),'},
                            {'number': 495,
                             'text': '    ("IBuffer_3_4_valid", (numValid >= (2 * (IBufSize / 4)).U) & '
                                     '(numValid < (3 * (IBufSize / 4)).U)),'},
                            {'number': 496,
                             'text': '    ("IBuffer_4_4_valid", (numValid >= (3 * (IBufSize / 4)).U) & '
                                     '(numValid < (4 * (IBufSize / 4)).U)),'},
                            {'number': 497, 'text': '    ("IBuffer_full     ", numValid.andR),'},
                            {'number': 498, 'text': '    ("Front_Bubble     ", FrontBubble),'},
                            {'number': 499, 'text': '    ("Fetch_Latency_Bound", fetchLatency)'},
                            {'number': 500, 'text': '  )'},
                            {'number': 501, 'text': '  generatePerfEvent()'},
                            {'number': 502, 'text': '}'}]},
 'tlb_events': {'file': 'src/main/scala/xiangshan/cache/mmu/TLB.scala',
                'sha256': '3dab2a7869968a57778cbab22b06f6fd13389dfde7cf3a800494255a6d8e0720',
                'lines': [{'number': 668,
                           'text': '  val result_ok = req_in.map(a => GatedValidRegNext(a.fire))'},
                          {'number': 669, 'text': '  val perfEvents ='},
                          {'number': 670, 'text': '    Seq('},
                          {'number': 671,
                           'text': '      ("access", PopCount((0 until Width).map{i => if (Block(i)) '
                                   'io.requestor(i).req.fire else portTranslateEnable(i) && result_ok(i) '
                                   '})),'},
                          {'number': 672,
                           'text': '      ("miss  ", PopCount((0 until Width).map{i => if (Block(i)) '
                                   'portTranslateEnable(i) && result_ok(i) && missVec(i) else '
                                   'ptw.req(i).fire })),'},
                          {'number': 673, 'text': '    )'},
                          {'number': 674, 'text': '  generatePerfEvent()'},
                          {'number': 675, 'text': ''},
                          {'number': 746, 'text': '  }'},
                          {'number': 747, 'text': '}'},
                          {'number': 748, 'text': ''},
                          {'number': 749,
                           'text': 'class TLBNonBlock(Width: Int, nRespDups: Int = 1, q: '
                                   'TLBParameters)(implicit p: Parameters) extends TLB(Width, nRespDups, '
                                   'Seq.fill(Width)(false), q)'},
                          {'number': 750,
                           'text': 'class TLBBLock(Width: Int, nRespDups: Int = 1, q: '
                                   'TLBParameters)(implicit p: Parameters) extends TLB(Width, nRespDups, '
                                   'Seq.fill(Width)(true), q)'}]},
 'frontend_tlb_route': {'file': 'src/main/scala/xiangshan/frontend/Frontend.scala',
                        'sha256': 'b260c45f11e23623547696f8ecbfb253090403abd72d6daaaceedaccdc70890b',
                        'lines': [{'number': 448, 'text': '  val csrevents = pfevent.io.hpmevent.take(8)'},
                                  {'number': 449, 'text': ''},
                                  {'number': 450,
                                   'text': '  val perfFromUnits = Seq(ifu, ibuffer, icache, ftq, '
                                           'bpu).flatMap(_.getPerfEvents)'},
                                  {'number': 451, 'text': '  val perfFromIO    = Seq()'},
                                  {'number': 452, 'text': '  val perfBlock     = Seq()'},
                                  {'number': 453,
                                   'text': '  val perfFromITLB  = itlb.getPerfEvents.map { case (str, idx) '
                                           '=> ("itlb_" + str, idx) }'},
                                  {'number': 454, 'text': '  // let index = 0 be no event'},
                                  {'number': 455,
                                   'text': '  val allPerfEvents = Seq(("noEvent", 0.U)) ++ perfFromUnits ++ '
                                           'perfFromIO ++ perfBlock ++ perfFromITLB'},
                                  {'number': 456, 'text': ''},
                                  {'number': 457, 'text': '  if (printEventCoding) {'}]},
 'dtlb_route': {'file': 'src/main/scala/xiangshan/mem/MemBlock.scala',
                'sha256': 'cc44d40afaa762b4b65fbab4350c9b4c1ab49c372de796f84680bddaa03ce411',
                'lines': [{'number': 699,
                           'text': '  val dtlb_ld_tlb_ld = Module(new TLBNonBlock(LduCnt + HyuCnt + 1 + '
                                   'MlsCnt, 2, ldtlbParams))'},
                          {'number': 700,
                           'text': '  val dtlb_st_tlb_st = Module(new TLBNonBlock(StaCnt, 1, sttlbParams))'},
                          {'number': 701,
                           'text': '  val dtlb_prefetch_tlb_prefetch = Module(new TLBNonBlock(2, 2, '
                                   'pftlbParams))'},
                          {'number': 702, 'text': '  val dtlb_ld = Seq(dtlb_ld_tlb_ld.io)'},
                          {'number': 703, 'text': '  val dtlb_st = Seq(dtlb_st_tlb_st.io)'},
                          {'number': 704, 'text': '  val dtlb_prefetch = Seq(dtlb_prefetch_tlb_prefetch.io)'},
                          {'number': 705, 'text': '  /* tlb vec && constant variable */'},
                          {'number': 706, 'text': '  val dtlb = dtlb_ld ++ dtlb_st ++ dtlb_prefetch'},
                          {'number': 707,
                           'text': '  val (dtlb_ld_idx, dtlb_st_idx, dtlb_pf_idx) = (0, 1, 2)'},
                          {'number': 708,
                           'text': '  val TlbSubSizeVec = Seq(LduCnt + HyuCnt + MlsCnt + 1, StaCnt, 2) // '
                                   '(load + hyu + mlsu + stream pf, store, sms+l2bop)'},
                          {'number': 709, 'text': '  val DTlbSize = TlbSubSizeVec.sum'},
                          {'number': 710,
                           'text': '  val TlbStartVec = TlbSubSizeVec.scanLeft(0)(_ + _).dropRight(1)'},
                          {'number': 711,
                           'text': '  val TlbEndVec = TlbSubSizeVec.scanLeft(0)(_ + _).drop(1)'},
                          {'number': 712, 'text': ''},
                          {'number': 713,
                           'text': '  val perfEventsDTLBld = dtlb_ld_tlb_ld.getPerfEvents.map { case (str, '
                                   'idx) => ("dtlb_ld_" + str, idx) }'},
                          {'number': 714,
                           'text': '  val perfEventsDTLBst = dtlb_st_tlb_st.getPerfEvents.map { case (str, '
                                   'idx) => ("dtlb_st_" + str, idx) }'},
                          {'number': 715, 'text': ''}]},
 'load_req_ports': {'file': 'src/main/scala/xiangshan/cache/dcache/loadpipe/LoadPipe.scala',
                    'sha256': 'da31d123f2e87dde49d7c2ae088d73737615c267a62fc6573ac77ce9a1779197',
                    'lines': [{'number': 654,
                               'text': '  XSPerfAccumulate("load_miss_or_conflict", io.lsu.resp.fire && '
                                       'resp.bits.miss)'},
                              {'number': 655,
                               'text': '  XSPerfAccumulate("actual_ld_fast_wakeup", s1_fire && '
                                       's1_tag_match_dup_dc && !io.disable_ld_fast_wakeup)'},
                              {'number': 656,
                               'text': '  XSPerfAccumulate("ideal_ld_fast_wakeup", io.banked_data_read.fire '
                                       '&& s1_tag_match_dup_dc)'},
                              {'number': 657, 'text': ''},
                              {'number': 658, 'text': '  val perfEvents = Seq('},
                              {'number': 659,
                               'text': '    ("load_req                 ", '
                                       'io.lsu.req.fire                                               ),'},
                              {'number': 660,
                               'text': '    ("load_replay              ", io.lsu.resp.fire && '
                                       'resp.bits.replay                          ),'},
                              {'number': 661,
                               'text': '    ("load_replay_for_data_nack", io.lsu.resp.fire && '
                                       'resp.bits.replay && s2_nack_data          ),'},
                              {'number': 662,
                               'text': '    ("load_replay_for_no_mshr  ", io.lsu.resp.fire && '
                                       'resp.bits.replay && s2_nack_no_mshr       ),'},
                              {'number': 663,
                               'text': '    ("load_replay_for_conflict ", io.lsu.resp.fire && '
                                       'resp.bits.replay && io.bank_conflict_slow ),'},
                              {'number': 664,
                               'text': '    ("l1D_read_dcache_access   ", io.lsu.resp.fire && '
                                       '!s2_is_prefetch                           ),'},
                              {'number': 665,
                               'text': '    ("l1D_read_dcache_miss     ", io.lsu.resp.fire && '
                                       '!s2_is_prefetch && real_miss              )'},
                              {'number': 666, 'text': '  )'}]},
 'l2_no_event': {'file': 'coupledL2/src/main/scala/coupledL2/CoupledL2.scala',
                 'sha256': 'eadb2b02f03b9d2a36aa34031bc8d14c2efdae48e5c9ada65804a242687844a6',
                 'lines': [{'number': 505,
                            'text': '    val perfEvents = Seq(("noEvent", 0.U)) ++ slices.zipWithIndex.map '
                                    '{'},
                           {'number': 506, 'text': '      case (slide, slide_idx) =>'},
                           {'number': 507,
                            'text': '        slide.getPerfEvents.map{case (str, idx) => ("Slice" + '
                                    'slide_idx.toString + "_" + str, idx)}'},
                           {'number': 508, 'text': '    }.flatten'},
                           {'number': 509, 'text': '    generatePerfEvent()'}]}}
EVENTS = {'frontend/ifu_req': {'predicate': 'io.toIbuffer.fire',
                      'unit': 'IFU-to-IBuffer packet handshakes',
                      'source_refs': ['ifu_new'],
                      'caveat': 'Counts delivered fetch packets, not retired instructions, cache lines or '
                                'DRAM accesses.'},
 'frontend/ifu_miss': {'predicate': 'io.toIbuffer.fire && !f3_perf_info.hit',
                       'unit': 'miss-tagged delivered fetch packets',
                       'source_refs': ['ifu_new'],
                       'caveat': 'Uses saved IFU perf-info hit, not raw ICache request misses or exclusive '
                                 'miss stall cycles.'},
 'frontend/mispredictRedirect': {'predicate': 'backendRedirect.valid && RedirectLevel.flushAfter === '
                                              'backendRedirect.bits.level',
                                 'unit': 'backend redirect predicate cycles',
                                 'source_refs': ['ftq_redirect'],
                                 'caveat': 'Only this redirect level is counted; not all frontend flushes or '
                                           'all mispredicted branches.'},
 'frontend/BpInstr': {'predicate': 'PopCount(commit_inst_mask & commit_cfi_mask)',
                      'unit': 'committed control-flow mask bits',
                      'source_refs': ['ftq_redirect'],
                      'caveat': 'Counts FTQ commit CFI-mask bits, not every branch-prediction lookup or '
                                'every retired instruction.'},
 'frontend/IBuffer_full': {'predicate': 'numValid.andR, where numValid = distanceBetween(enqPtr, deqPtr)',
                           'unit': 'all-ones occupancy-encoding predicate cycles',
                           'source_refs': ['ibuffer_full'],
                           'caveat': 'Reduction AND of occupancy encoding, not numValid == IBufSize or '
                                     '!allowEnq. This is not a conventional buffer-full stall fraction.'},
 'frontend/itlb_access': {'predicate': 'PopCount over ports: if Block(i), requestor(i).req.fire; else '
                                       'portTranslateEnable(i) && result_ok(i)',
                          'unit': 'TLB port access increments',
                          'source_refs': ['tlb_events', 'frontend_tlb_route'],
                          'caveat': 'Per-port blocking policy changes the qualifier; not unique instructions '
                                    'or bytes.'},
 'frontend/itlb_miss': {'predicate': 'PopCount over ports: if Block(i), portTranslateEnable(i) && '
                                     'result_ok(i) && missVec(i); else ptw.req(i).fire',
                        'unit': 'TLB miss-path increments',
                        'source_refs': ['tlb_events', 'frontend_tlb_route'],
                        'caveat': 'Blocking and nonblocking ports count at different boundaries; not latency '
                                  'or a fraction of all memory accesses.'},
 'memblock/load_req': {'predicate': 'io.lsu.req.fire in each selected DCache load pipe',
                       'unit': 'DCache load-pipe handshakes',
                       'source_refs': ['load_req_ports'],
                       'caveat': 'May include replays; sums of ports count accepted requests, not unique '
                                 'retired loads or transferred bytes.'},
 'memblock/dtlb_ld_miss': {'predicate': 'PopCount(ptw.req(i).fire); TLBNonBlock uses Block=false for all '
                                        'load ports',
                           'unit': 'load-side PTW-request handshakes',
                           'source_refs': ['tlb_events', 'dtlb_route'],
                           'caveat': 'Accepted translation-walk requests, not every lookup miss, retired '
                                     'load or unique page.'},
 'memblock/dtlb_st_miss': {'predicate': 'PopCount(ptw.req(i).fire); TLBNonBlock uses Block=false for all '
                                        'store ports',
                           'unit': 'store-side PTW-request handshakes',
                           'source_refs': ['tlb_events', 'dtlb_route'],
                           'caveat': 'Accepted translation-walk requests, not every lookup miss, retired '
                                     'store or unique page.'},
 'l2 cache/noEvent': {'predicate': 'Constant zero increment: perfEvents begins with ("noEvent", 0.U), '
                                   'exposed through the L2 perf IO',
                      'unit': 'zero',
                      'source_refs': ['l2_no_event'],
                      'caveat': 'The recorded signal is the L2 IO wrapper, not a direct UInt literal. This '
                                'exact build/group/id/signal binding is required.'}}
CODING = {'l2 cache/0': {'name': 'noEvent', 'signal': 'TL2TLCoupledL2.io_perf[0].value: IO[UInt<6>]'}}

"""Reviewed RTL source contract. See docs/hardware-analysis.md for provenance.

Source excerpts retain upstream Mulan PSL v2 notices by reference to each file.
These data describe a pinned RTL build, never arbitrary similarly named events.
"""
CONTRACT = {'id': 'xsai-default-matrix-store-fix-20261026/v1',
 'source_identity_scope': 'Build producer hashes git diff HEAD -- src build.sc for each repo. Exact '
                          'emulator hash and build-log hash bind this review to the archived build; '
                          'excerpts are explanations, not a proof of independent rebuild '
                          'reproducibility.',
 'build': {'emulator_sha256': '189681b2f3aa6fe9f51891acd9df0bb51b250305ecd970f2d0b26a619541adfd',
           'build_log_sha256': '2dbf4d47997a0a4d94d8f90807a64828e1fce538e8045c83b03fbe9dca549d2c',
           'configuration': {'CONFIG': 'DefaultMatrixConfig',
                             'NUM_CORES': '1',
                             'ISSUE': 'E.b',
                             'WITH_DRAMSIM3': '1',
                             'WITH_CHISELDB': '1',
                             'WITH_CONSTANTIN': '0',
                             'EMU_THREADS': '8',
                             'EMU_TRACE': 'fst',
                             'RELEASE': '0'},
           'sources': [{'role': 'core',
                        'revision': '04909692a1cdc6b9165b95c7ea83b94bdc01ab39',
                        'diff_sha256': 'bfcf8072ff224c65023ab711c10c98734fa62b3588bb92eac2630b1564fef7ac'},
                       {'role': 'utility',
                        'revision': '5d61bcb44fb01ae98b0f70c072b9c50c10ca09a7',
                        'diff_sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'},
                       {'role': 'cute',
                        'revision': 'de31b2d23f042ff3e5bddc93b7f9ceb0e9263122',
                        'diff_sha256': '56e532745d5fb46868d77c3fc4044054c960fffe44d6fcae42465619ebcc7987'},
                       {'role': 'l2',
                        'revision': '7b690d4dd48adbee8cb31e78a6df3fdfaf863d5a',
                        'diff_sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'}]},
 'sources': {'lifetime': {'file': 'utility/src/main/scala/utility/ChiselTaggedTrace.scala',
                          'sha256': 'e88936620a95e56f6e071332615b03883fe320e3b1ee5438ef94565368c17336',
                          'lines': [{'number': 599, 'text': '       |  }'},
                                    {'number': 600, 'text': '       |}'},
                                    {'number': 601, 'text': '       |'},
                                    {'number': 602, 'text': '       |extern "C" {'},
                                    {'number': 603,
                                     'text': '       |  // dpic function name must same as HasDPICUtils '
                                             "subclass's name"},
                                    {'number': 604, 'text': '       |  // here add your new interface'},
                                    {'number': 605, 'text': '       |'},
                                    {'number': 606, 'text': '       |  void globalSimNegedge() {'},
                                    {'number': 607, 'text': '       |    global_tick_acc++;'},
                                    {'number': 608, 'text': '       |    perfCCT->tick();'},
                                    {'number': 609, 'text': '       |  }'},
                                    {'number': 610, 'text': '       |'},
                                    {'number': 611,
                                     'text': '       |  uint64_t createInstMeta(uint64_t order_id, '
                                             'uint64_t pc, uint64_t instcode) {'},
                                    {'number': 612,
                                     'text': '       |    return perfCCT->createInstMeta(order_id, pc, '
                                             'instcode);'}]},
             'lifetime_helper': {'file': 'utility/src/main/scala/utility/ChiselTaggedTrace.scala',
                                 'sha256': 'e88936620a95e56f6e071332615b03883fe320e3b1ee5438ef94565368c17336',
                                 'lines': [{'number': 65,
                                            'text': '         |${if (has_out) ",\\noutput [63:0]" + '
                                                    'port_output else ""}'},
                                           {'number': 66,
                                            'text': '         |${if (has_in) ports_input.map(x => '
                                                    '"input [63:0] " + x).mkString(",", ",\\n", "") '
                                                    'else ""}'},
                                           {'number': 67, 'text': '         |);'},
                                           {'number': 68,
                                            'text': '         |  ${if (has_out) "reg [63: 0] " + '
                                                    'out_reg + ";" else ""}'},
                                           {'number': 69, 'text': '         |  always@($clock) begin'},
                                           {'number': 70, 'text': '         |    if (reset) begin'},
                                           {'number': 71,
                                            'text': '         |      ${if (has_out) out_reg + assign + '
                                                    '"0" else ""};'},
                                           {'number': 72, 'text': '         |    end'},
                                           {'number': 73, 'text': '         |    else if(en) begin'},
                                           {'number': 74,
                                            'text': '         |      ${if (has_out) out_reg + assign '
                                                    'else "  "}$dpicFunc(${ports_input.mkString("", ", '
                                                    '", "")});'},
                                           {'number': 75, 'text': '         |    end'},
                                           {'number': 76, 'text': '         |    else begin'},
                                           {'number': 77,
                                            'text': '         |      ${if (comb_output) out_reg + '
                                                    'assign + "0" else ""};'},
                                           {'number': 78, 'text': '         |    end'},
                                           {'number': 79, 'text': '         |  end'},
                                           {'number': 80, 'text': '         |'},
                                           {'number': 81,
                                            'text': '         |  ${if (has_out) "assign " + port_output '
                                                    '+ " = " + out_reg + ";" else ""}'},
                                           {'number': 82, 'text': '         |endmodule'},
                                           {'number': 83, 'text': '         |""".stripMargin'}]},
             'cpu_tick': {'file': 'src/main/scala/xiangshan/backend/rob/Rob.scala',
                          'sha256': '0617422c36ed26024d9f6e1373581a5350cb478a0cf7a1aea8e93d2f83afa3e0',
                          'lines': [{'number': 158,
                                     'text': '  val csrWBs = io.exuWriteback.filter(x => '
                                             'x.bits.params.hasCSR).toSeq'},
                                    {'number': 159, 'text': ''},
                                    {'number': 160, 'text': '  PerfCCT.tick(clock, reset)'},
                                    {'number': 161, 'text': ''},
                                    {'number': 162,
                                     'text': '  io.exuWriteback.zipWithIndex.foreach{ case (wb, i) '
                                             '=>'}]},
             'database': {'file': 'utility/src/main/scala/utility/ChiselDB.scala',
                          'sha256': '681b32a7268c5b83114396f06e56bd8020defecbf4579c8c9676ca1b85504ac6',
                          'lines': [{'number': 147,
                                     'text': '  def log(data: T, en: Bool, site: String = "", clock: '
                                             'Clock, reset: Reset): Unit = {'},
                                    {'number': 148, 'text': '    if(!envInFPGA){'},
                                    {'number': 149,
                                     'text': '      val writer = Module(new '
                                             'TableWriteHelper[T](tableName, hw, site))'},
                                    {'number': 150, 'text': '      val cnt = RegInit(0.U(64.W))'},
                                    {'number': 151, 'text': '      cnt := cnt + 1.U'},
                                    {'number': 152, 'text': '      writer.io.clock := clock'},
                                    {'number': 153, 'text': '      writer.io.reset := reset'},
                                    {'number': 154, 'text': '      writer.io.en := en'},
                                    {'number': 155, 'text': '      writer.io.stamp := cnt'},
                                    {'number': 156, 'text': '      writer.io.data := data'},
                                    {'number': 157, 'text': '    }'},
                                    {'number': 158, 'text': '  }'},
                                    {'number': 159, 'text': ''},
                                    {'number': 160,
                                     'text': '  def log(data: Valid[T], site: String, clock: Clock, '
                                             'reset: Reset): Unit = {'}]},
             'database_writer': {'file': 'utility/src/main/scala/utility/ChiselDB.scala',
                                 'sha256': '681b32a7268c5b83114396f06e56bd8020defecbf4579c8c9676ca1b85504ac6',
                                 'lines': [{'number': 212,
                                            'text': '       |  always@(posedge clock) begin'},
                                           {'number': 213, 'text': '       |    if(en && !reset) begin'},
                                           {'number': 214,
                                            'text': '       |      '
                                                    '$dpicFunc(${table.map(_.vExpr).mkString("", ", ", '
                                                    '", stamp, site")});'},
                                           {'number': 215, 'text': '       |    end'},
                                           {'number': 216, 'text': '       |  end'},
                                           {'number': 217, 'text': '       |endmodule'},
                                           {'number': 218, 'text': '       |""".stripMargin'}]},
             'cute_sites': {'file': 'CUTE/src/main/scala/TaskController.scala',
                            'sha256': '6ac6532d648e87d6ba0961382fe2bd540d5810048adf96a84351184087e204d2',
                            'lines': [{'number': 1452,
                                       'text': '  loadEventTable.log(loadAllocateEvent, '
                                               'loadAllocateEventEn, "LoadAllocate", clock, reset)'},
                                      {'number': 1453,
                                       'text': '  loadEventTable.log(loadIssueEvent, loadIssueEventEn, '
                                               '"LoadIssue", clock, reset)'},
                                      {'number': 1454,
                                       'text': '  loadEventTable.log(loadAFinishEvent, '
                                               'loadAFinishEventEn, "LoadFinish", clock, reset)'},
                                      {'number': 1455,
                                       'text': '  loadEventTable.log(loadBFinishEvent, '
                                               'loadBFinishEventEn, "LoadFinish", clock, reset)'},
                                      {'number': 1456,
                                       'text': '  loadEventTable.log(loadCFinishEvent, '
                                               'loadCFinishEventEn, "LoadFinish", clock, reset)'},
                                      {'number': 1457, 'text': ''},
                                      {'number': 1458,
                                       'text': '  computeEventTable.log(computeIssueEvent, '
                                               'computeIssueEventEn, "ComputeIssue", clock, reset)'},
                                      {'number': 1459,
                                       'text': '  computeEventTable.log(computeReadAFinishEvent, '
                                               'computeReadAFinishEventEn, "ComputeReadAFinish", clock, '
                                               'reset)'},
                                      {'number': 1460,
                                       'text': '  computeEventTable.log(computeReadBFinishEvent, '
                                               'computeReadBFinishEventEn, "ComputeReadBFinish", clock, '
                                               'reset)'},
                                      {'number': 1461,
                                       'text': '  computeEventTable.log(computeWriteCFinishEvent, '
                                               'computeWriteCFinishEventEn, "ComputeWriteCFinish", '
                                               'clock, reset)'},
                                      {'number': 1462, 'text': ''},
                                      {'number': 1463,
                                       'text': '  storeEventTable.log(storeIssueEvent, '
                                               'storeIssueEventEn, "StoreIssue", clock, reset)'},
                                      {'number': 1464,
                                       'text': '  storeEventTable.log(storeFinishEvent, '
                                               'storeFinishEventEn, "StoreFinish", clock, reset)'},
                                      {'number': 1465, 'text': ''},
                                      {'number': 1466,
                                       'text': '  releaseEventTable.log(releaseIssueEvent, '
                                               'releaseIssueEventEn, "ReleaseIssue", clock, reset)'},
                                      {'number': 1467, 'text': ''}]},
             'hpm_composition': {'file': 'utility/src/main/scala/utility/HardwarePerfMonitor.scala',
                                 'sha256': '173cd98a55c2273bde797650d54e297095201e6a50cad210937e8434b0d57c84',
                                 'lines': [{'number': 61,
                                            'text': '  def combineEvents(cnt_1: UInt, cnt_2: UInt, '
                                                    'optype: UInt): UInt ='},
                                           {'number': 62, 'text': '    Mux(optype(0), cnt_1 & cnt_2,'},
                                           {'number': 63, 'text': '    Mux(optype(1), cnt_1 ^ cnt_2,'},
                                           {'number': 64, 'text': '    Mux(optype(2), cnt_1 + cnt_2,'},
                                           {'number': 65, 'text': '                   cnt_1 | cnt_2)))'},
                                           {'number': 66, 'text': ''},
                                           {'number': 67,
                                            'text': '  val event_step_0 = '
                                                    'combineEvents(events_incr_0.value, '
                                                    'events_incr_1.value, event_op_0)'},
                                           {'number': 68,
                                            'text': '  val event_step_1 = '
                                                    'combineEvents(events_incr_2.value, '
                                                    'events_incr_3.value, event_op_1)'},
                                           {'number': 69, 'text': ''},
                                           {'number': 70,
                                            'text': '  // add registers to optimize the timing (like '
                                                    'pipelines)'},
                                           {'number': 71,
                                            'text': '  val event_op_2_reg = RegNext(event_op_2)'},
                                           {'number': 72,
                                            'text': '  val event_step_0_reg = RegNext(event_step_0)'},
                                           {'number': 73,
                                            'text': '  val event_step_1_reg = RegNext(event_step_1)'},
                                           {'number': 74,
                                            'text': '  val selected = combineEvents(event_step_0_reg, '
                                                    'event_step_1_reg, event_op_2_reg)'},
                                           {'number': 75, 'text': ''},
                                           {'number': 76,
                                            'text': '  val perfEvents = Seq(("selected", selected))'},
                                           {'number': 77, 'text': '  generatePerfEvent()'},
                                           {'number': 78, 'text': '}'},
                                           {'number': 79, 'text': ''},
                                           {'number': 80,
                                            'text': 'class HPerfMonitor(numCSRPCnt: Int, numPCnt: '
                                                    'Int)(implicit p: Parameters) extends Module with '
                                                    'HasPerfEvents {'}]},
             'hpm_register': {'file': 'utility/src/main/scala/utility/HardwarePerfMonitor.scala',
                              'sha256': '173cd98a55c2273bde797650d54e297095201e6a50cad210937e8434b0d57c84',
                              'lines': [{'number': 31,
                                         'text': '  def generatePerfEvent(noRegNext: Option[Seq[Int]] = '
                                                 'None): Unit = {'},
                                        {'number': 32,
                                         'text': '    for (((out, (name, counter)), i) <- '
                                                 'io_perf.zip(perfEvents).zipWithIndex) {'},
                                        {'number': 33, 'text': '      require(!name.contains("/"))'},
                                        {'number': 34,
                                         'text': '      out.value := RegNext(RegNext(counter))'},
                                        {'number': 35,
                                         'text': '      if (noRegNext.isDefined && '
                                                 'noRegNext.get.contains(i)) {'},
                                        {'number': 36, 'text': '        out.value := counter'},
                                        {'number': 37, 'text': '      }'},
                                        {'number': 38, 'text': '    }'},
                                        {'number': 39, 'text': '  }'},
                                        {'number': 40,
                                         'text': '  def getPerfEvents: Seq[(String, UInt)] = {'}]},
             'hpm_accumulation': {'file': 'src/main/scala/xiangshan/backend/fu/CSR.scala',
                                  'sha256': '9a2a54a994a41e41c47bb63680dbb6c96cd101684413fe01827b9e27ef630e48',
                                  'lines': [{'number': 789, 'text': '  for(i <- 0 until 29){'},
                                            {'number': 790,
                                             'text': '    perfCnts(i) := Mux(mcountinhibit(i+3) | '
                                                     '!perfEventscounten(i), perfCnts(i), perfCnts(i) + '
                                                     'perf_events(i).value)'},
                                            {'number': 791, 'text': '  }'},
                                            {'number': 792, 'text': ''}]},
             'datapath': {'file': 'src/main/scala/xiangshan/backend/datapath/DataPath.scala',
                          'sha256': 'ab6ade87025ae2859adf81ef5e59904549ec5d56e8cccbfc16306916b6dab983',
                          'lines': [{'number': 968,
                                     'text': '  val uopsIssued = fromIQ.flatten.map(_.fire).reduce(_ || '
                                             '_)'},
                                    {'number': 969,
                                     'text': '  val uopsIssuedCnt = '
                                             'PopCount(fromIQ.flatten.map(_.fire))'},
                                    {'number': 970,
                                     'text': '  val fewUopsIssued = (0 until FewUops).map(_.U === '
                                             'uopsIssuedCnt).reduce(_ || _)'},
                                    {'number': 971, 'text': ''},
                                    {'number': 972, 'text': '  val stallLoad = !uopsIssued'},
                                    {'number': 973, 'text': ''},
                                    {'number': 974,
                                     'text': '  val noStoreIssued = !fromMemIQ.flatten.filter(memIq => '
                                             'memIq.bits.exuParams.fuConfigs.contains(FuConfig.StaCfg) '
                                             '||'},
                                    {'number': 975,
                                     'text': '                                                         '
                                             'memIq.bits.exuParams.fuConfigs.contains(FuConfig.StdCfg)'},
                                    {'number': 976, 'text': '  ).map(_.fire).reduce(_ || _)'},
                                    {'number': 977,
                                     'text': '  val stallStore = uopsIssued && noStoreIssued'},
                                    {'number': 978, 'text': ''},
                                    {'number': 979, 'text': '  val stallLoadReg = DelayN(stallLoad, 2)'},
                                    {'number': 980,
                                     'text': '  val stallStoreReg = DelayN(stallStore, 2)'},
                                    {'number': 981, 'text': ''},
                                    {'number': 982,
                                     'text': '  val memStallAnyLoad = stallLoadReg && !lqEmpty'},
                                    {'number': 983,
                                     'text': '  val memStallStore = stallStoreReg && !sqEmpty'},
                                    {'number': 984,
                                     'text': '  val memStallL1Miss = memStallAnyLoad && l1Miss'},
                                    {'number': 985,
                                     'text': '  val memStallL2Miss = memStallL1Miss && l2Miss'},
                                    {'number': 986,
                                     'text': '  val memStallL3Miss = memStallL2Miss && l3Miss'},
                                    {'number': 987, 'text': ''},
                                    {'number': 988,
                                     'text': '  io.topDownInfo.noUopsIssued := stallLoad'},
                                    {'number': 989, 'text': ''},
                                    {'number': 990,
                                     'text': '  XSPerfAccumulate("exec_stall_cycle",   fewUopsIssued)'},
                                    {'number': 991,
                                     'text': '  XSPerfAccumulate("mem_stall_store",    memStallStore)'},
                                    {'number': 992,
                                     'text': '  XSPerfAccumulate("mem_stall_l1miss",   memStallL1Miss)'},
                                    {'number': 993,
                                     'text': '  XSPerfAccumulate("mem_stall_l2miss",   memStallL2Miss)'},
                                    {'number': 994,
                                     'text': '  XSPerfAccumulate("mem_stall_l3miss",   memStallL3Miss)'},
                                    {'number': 995, 'text': ''},
                                    {'number': 996, 'text': '  val perfEvents = Seq('},
                                    {'number': 997, 'text': '    ("EXEC_STALL_CYCLE",  fewUopsIssued),'},
                                    {'number': 998, 'text': '    ("MEMSTALL_STORE",    memStallStore),'},
                                    {'number': 999,
                                     'text': '    ("MEMSTALL_L1MISS",   memStallL1Miss),'},
                                    {'number': 1000,
                                     'text': '    ("MEMSTALL_L2MISS",   memStallL2Miss),'},
                                    {'number': 1001,
                                     'text': '    ("MEMSTALL_L3MISS",   memStallL3Miss),'},
                                    {'number': 1002, 'text': '  )'},
                                    {'number': 1003, 'text': '  generatePerfEvent()'},
                                    {'number': 1004, 'text': '}'},
                                    {'number': 1005, 'text': ''},
                                    {'number': 1006,
                                     'text': 'class DataPathIO()(implicit p: Parameters, params: '
                                             'BackendParams) extends XSBundle {'},
                                    {'number': 1007, 'text': '  // params'},
                                    {'number': 1008,
                                     'text': '  private val intSchdParams = '
                                             'params.schdParams(IntScheduler())'},
                                    {'number': 1009,
                                     'text': '  private val fpSchdParams = '
                                             'params.schdParams(FpScheduler())'},
                                    {'number': 1010,
                                     'text': '  private val vfSchdParams = '
                                             'params.schdParams(VfScheduler())'},
                                    {'number': 1011,
                                     'text': '  private val mfSchdParams = '
                                             'params.schdParams(MfScheduler())'},
                                    {'number': 1012,
                                     'text': '  private val memSchdParams = '
                                             'params.schdParams(MemScheduler())'}]},
             'scheduler': {'file': 'src/main/scala/xiangshan/backend/issue/Scheduler.scala',
                           'sha256': '183fac546bd3b26dfc6169dbc50646d7e816ce2f9e994335b430e029937071cc',
                           'lines': [{'number': 341,
                                      'text': '  val lastCycleIqEnqFireVec    = '
                                              'RegNext(VecInit(issueQueues.map(_.io.enq.map(_.fire)).flatten))'},
                                     {'number': 342,
                                      'text': '  val lastCycleIqFullVec       = '
                                              'RegNext(VecInit(issueQueues.map(_.io.enq.head.ready)))'},
                                     {'number': 343, 'text': ''},
                                     {'number': 344,
                                      'text': '  val issueQueueFullVecPerf = '
                                              'issueQueues.zip(lastCycleIqFullVec)map{ case (iq, full) '
                                              '=> (iq.params.getIQName + s"_full", full) }'},
                                     {'number': 345, 'text': '  val basePerfEvents = Seq('},
                                     {'number': 346,
                                      'text': '    ("issueQueue_enq_fire_cnt",  '
                                              'PopCount(lastCycleIqEnqFireVec)                    )'},
                                     {'number': 347, 'text': '  )  ++ issueQueueFullVecPerf'},
                                     {'number': 348, 'text': ''},
                                     {'number': 349,
                                      'text': '  println(s"[Scheduler] io.fromSchedulers.wakeupVec: '
                                              '${io.fromSchedulers.wakeupVec.map(x => '
                                              'backendParams.getExuName(x.bits.exuIdx))}")'}]},
             'loadpipe': {'file': 'src/main/scala/xiangshan/cache/dcache/loadpipe/LoadPipe.scala',
                          'sha256': 'da31d123f2e87dde49d7c2ae088d73737615c267a62fc6573ac77ce9a1779197',
                          'lines': [{'number': 663,
                                     'text': '    ("load_replay_for_conflict ", io.lsu.resp.fire && '
                                             'resp.bits.replay && io.bank_conflict_slow ),'},
                                    {'number': 664,
                                     'text': '    ("l1D_read_dcache_access   ", io.lsu.resp.fire && '
                                             '!s2_is_prefetch                           ),'},
                                    {'number': 665,
                                     'text': '    ("l1D_read_dcache_miss     ", io.lsu.resp.fire && '
                                             '!s2_is_prefetch && real_miss              )'},
                                    {'number': 666, 'text': '  )'},
                                    {'number': 667, 'text': '  generatePerfEvent()'}]},
             'writepipe': {'file': 'src/main/scala/xiangshan/cache/dcache/mainpipe/MainPipe.scala',
                           'sha256': 'd0d2306f89296fe7cdfe89984a01fbb99efd7802ef5705bf560c498cdc62e6e6',
                           'lines': [{'number': 1074,
                                      'text': '    ("l1D_write_dcache_access", s2_fire && (s2_isStore '
                                              '|| (s2_isAMO && isWrite(s2_req.cmd)))), // store_req '
                                              '(cacheline evited from Sbuffer to L1D) & amo write'},
                                     {'number': 1075,
                                      'text': '    ("l1D_write_dcache_miss  ", s2_fire && (s2_isStore '
                                              '|| (s2_isAMO && isWrite(s2_req.cmd)) && !s2_hit)),'},
                                     {'number': 1076,
                                      'text': '    ("dcache_mp_req          ", '
                                              's0_fire                                                      '
                                              '),'}]},
             'memblock': {'file': 'src/main/scala/xiangshan/mem/MemBlock.scala',
                          'sha256': 'cc44d40afaa762b4b65fbab4350c9b4c1ab49c372de796f84680bddaa03ce411',
                          'lines': [{'number': 2187,
                                     'text': '  val hyLdDeqCount = '
                                             'PopCount(io.ooo_to_mem.issueHya.map(x => x.valid && '
                                             'FuType.isLoad(x.bits.uop.fuType)))'},
                                    {'number': 2188,
                                     'text': '  val hyStDeqCount = '
                                             'PopCount(io.ooo_to_mem.issueHya.map(x => x.valid && '
                                             'FuType.isStore(x.bits.uop.fuType)))'},
                                    {'number': 2189,
                                     'text': '  val ldDeqCount = '
                                             'PopCount(io.ooo_to_mem.issueLda.map(_.valid)) +& '
                                             'hyLdDeqCount'},
                                    {'number': 2190,
                                     'text': '  val stDeqCount = '
                                             'PopCount(io.ooo_to_mem.issueSta.take(StaCnt).map(_.valid)) '
                                             '+& hyStDeqCount'},
                                    {'number': 2191,
                                     'text': '  val iqDeqCount = ldDeqCount +& stDeqCount'},
                                    {'number': 2192,
                                     'text': '  XSPerfAccumulate("load_iq_deq_count", ldDeqCount)'},
                                    {'number': 2193,
                                     'text': '  XSPerfHistogram("load_iq_deq_count", ldDeqCount, '
                                             'true.B, 0, LdExuCnt + 1)'},
                                    {'number': 2194,
                                     'text': '  XSPerfAccumulate("store_iq_deq_count", stDeqCount)'},
                                    {'number': 2195,
                                     'text': '  XSPerfHistogram("store_iq_deq_count", stDeqCount, '
                                             'true.B, 0, StAddrCnt + 1)'}]},
             'replay': {'file': 'src/main/scala/xiangshan/mem/lsqueue/LoadQueueReplay.scala',
                        'sha256': 'd0ec926218dc03381816f185bd7e21ead0109a6fc66a81c54053a9a38fd288fb',
                        'lines': [{'number': 817,
                                   'text': '  val replayBankConflictCount = PopCount(io.enq.map(enq => '
                                           'enq.fire && !enq.bits.isLoadReplay && '
                                           'enq.bits.rep_info.cause(LoadReplayCauses.C_BC)))'},
                                  {'number': 818,
                                   'text': '  val replayDCacheReplayCount = PopCount(io.enq.map(enq => '
                                           'enq.fire && !enq.bits.isLoadReplay && '
                                           'enq.bits.rep_info.cause(LoadReplayCauses.C_DR)))'}]},
             'rob_load': {'file': 'src/main/scala/xiangshan/backend/rob/Rob.scala',
                          'sha256': '0617422c36ed26024d9f6e1373581a5350cb478a0cf7a1aea8e93d2f83afa3e0',
                          'lines': [{'number': 1791,
                                     'text': '    ("rob_commitInstrLoad    ", '
                                             'ifCommitReg(PopCount(RegEnable(commitLoadVec, '
                                             'isCommit)))),'},
                                    {'number': 1792,
                                     'text': '    ("rob_commitInstrBranch  ", '
                                             'ifCommitReg(PopCount(RegEnable(commitBranchVec, '
                                             'isCommit)))),'}]},
             'ibuffer': {'file': 'src/main/scala/xiangshan/frontend/IBuffer.scala',
                         'sha256': 'f6fddab79e5389950c0414d60d10cad2c1f6679ac05a7554ce2f5855dde48974',
                         'lines': [{'number': 474,
                                    'text': '  val instrHungry = afterInit && (numValid === 0.U) && '
                                            '!headBubble'},
                                   {'number': 475, 'text': ''},
                                   {'number': 476, 'text': '  QueuePerf(IBufSize, numValid, !allowEnq)'},
                                   {'number': 477, 'text': '  XSPerfAccumulate("flush", io.flush)'}]},
             'l2': {'file': 'coupledL2/src/main/scala/coupledL2/tl2tl/MainPipe.scala',
                    'sha256': 'cf3e5b1097e3bb017418f0dd3bb227babff035aec61a098626fb1ca17bf4cfbb',
                    'lines': [{'number': 866,
                               'text': '    ("l2_cache_access_rd", task_s3.valid && sinkA_req_s3 && '
                                       '!req_prefetch_s3),'},
                              {'number': 867,
                               'text': '    ("l2_cache_access_wr", task_s3.valid && sinkC_req_s3),'},
                              {'number': 868,
                               'text': '    ("l2_cache_miss_rd", task_s3.valid && sinkA_req_s3 && '
                                       '!req_prefetch_s3 && miss_s3),'},
                              {'number': 869,
                               'text': '    //    ("l2_cache_miss_wr", Inclusive L2 always hit),'},
                              {'number': 870,
                               'text': '    ("l2_cache_inv", task_s3.valid && sinkB_req_s3 && '
                                       '(req_s3.param === toN))'}]},
             'l2_refill': {'file': 'coupledL2/src/main/scala/coupledL2/tl2tl/MSHRCtl.scala',
                           'sha256': 'cdf90ec904e43fb3eb366eade39bffc6e0c5d396e0f0c2430b09ed78d835c790',
                           'lines': [{'number': 342,
                                      'text': '    ("l2_cache_refill", acquireUnit.io.sourceA.fire && '
                                              'acquireUnit.io.task.bits.opcode === AcquireBlock),'},
                                     {'number': 343,
                                      'text': '    ("l2_cache_rd_refill", acquireUnit.io.sourceA.fire '
                                              '&& acquireUnit.io.task.bits.opcode === AcquireBlock),'}]},
             'ldu_stall': {'file': 'src/main/scala/xiangshan/mem/pipeline/LoadUnit.scala',
                           'sha256': '155800b693001aafc4f1683613533c48a4b0326552abfd8330f1e54942c0b277',
                           'lines': [{'number': 1979,
                                      'text': '    ("stall_dcache            ", s0_valid && s0_can_go '
                                              '&& !io.dcache.req.ready                  ),'}]},
             'backend_order': {'file': 'src/main/scala/xiangshan/backend/Backend.scala',
                               'sha256': 'ba41c63a7e37ad23e724207ab9eb297492fc3e224260d041e126edf78023a904',
                               'lines': [{'number': 187,
                                          'text': '  val intScheduler = params.intSchdParams.map(x => '
                                                  'LazyModule(new Scheduler(x)))'},
                                         {'number': 188,
                                          'text': '  val fpScheduler = params.fpSchdParams.map(x => '
                                                  'LazyModule(new Scheduler(x)))'},
                                         {'number': 189,
                                          'text': '  val vfScheduler = params.vfSchdParams.map(x => '
                                                  'LazyModule(new Scheduler(x)))'},
                                         {'number': 190,
                                          'text': '  val mfScheduler = '
                                                  'Option.when(HasMatrixExtension)(params.mfSchdParams.map(x '
                                                  '=> LazyModule(new Scheduler(x))))'},
                                         {'number': 191,
                                          'text': '  val memScheduler = params.memSchdParams.map(x => '
                                                  'LazyModule(new Scheduler(x)))'}]},
             'default_config': {'file': 'src/main/scala/top/Configs.scala',
                                'sha256': 'fd6ba2f495fe4a0c5648b3f4bed4331907abf541d320327704add27241a2efcd',
                                'lines': [{'number': 532,
                                           'text': 'class DefaultMatrixConfig(n: Int = 1) extends '
                                                   'Config('},
                                          {'number': 533,
                                           'text': '  new DefaultConfig(n).alter((site, here, up) => {'},
                                          {'number': 534,
                                           'text': '    case XSTileKey => up(XSTileKey).map { p =>'},
                                          {'number': 535, 'text': '      p.copy('},
                                          {'number': 536, 'text': '        TLEN = 128 * 64 * 8,'},
                                          {'number': 537, 'text': '        TRLEN = 64 * 8,'},
                                          {'number': 538, 'text': '        MELEN = 32,'},
                                          {'number': 539,
                                           'text': '        MatrixExtension = MatrixIsaParams('},
                                          {'number': 540, 'text': '          enableInt8Int32 = true,'},
                                          {'number': 541, 'text': '          enableFp8Fp32 = true,'},
                                          {'number': 542, 'text': '          enableFp8Fp16 = true,'},
                                          {'number': 543, 'text': '          enableFp8Bf16 = true,'},
                                          {'number': 544, 'text': '          enableFp16Fp16 = true,'}]},
             'chi_default': {'file': 'coupledL2/src/main/scala/coupledL2/L2Param.scala',
                             'sha256': 'a44df390db1fef114042a5e0eb6f19340509e64c3c5fc70064fafe62e9f9463e',
                             'lines': [{'number': 30,
                                        'text': 'case object EnableCHI extends '
                                                'Field[Boolean](false)'}]}},
 'events': {'frontend/noEvent': {'predicate': 'Constant zero increment',
                                 'unit': 'zero',
                                 'source_refs': ['hpm_composition']},
            'backend/noEvent': {'predicate': 'Constant zero increment',
                                'unit': 'zero',
                                'source_refs': ['hpm_composition']},
            'memblock/noEvent': {'predicate': 'Constant zero increment',
                                 'unit': 'zero',
                                 'source_refs': ['hpm_composition']},
            'l2 cache/noEvent': {'predicate': 'Constant zero increment',
                                 'unit': 'zero',
                                 'source_refs': ['hpm_composition']},
            'backend/EXEC_STALL_CYCLE': {'predicate': 'PopCount(fromIQ.flatten.map(_.fire)) < 4',
                                         'unit': 'predicate cycles',
                                         'source_refs': ['datapath'],
                                         'caveat': 'Counts cycles issuing fewer than four uops, '
                                                   'including one to three. It does not mean zero issue '
                                                   'or an exclusive execution stall.'},
            'backend/MEMSTALL_STORE': {'predicate': 'DelayN(any uop issued AND no '
                                                    'store-address/store-data fire, 2) AND NOT sqEmpty',
                                       'unit': 'predicate cycles',
                                       'source_refs': ['datapath'],
                                       'caveat': 'Can be true while other work issues. It is not proof '
                                                 'the core is blocked by stores.'},
            'backend/MEMSTALL_L1MISS': {'predicate': 'DelayN(no uops issued, 2) AND NOT lqEmpty AND '
                                                     'l1Miss',
                                        'unit': 'predicate cycles',
                                        'source_refs': ['datapath'],
                                        'caveat': 'Nested predicates overlap across L1/L2/L3; do not '
                                                  'sum them into a stall partition.'},
            'backend/MEMSTALL_L2MISS': {'predicate': 'DelayN(no uops issued, 2) AND NOT lqEmpty AND '
                                                     'l1Miss AND l2Miss',
                                        'unit': 'predicate cycles',
                                        'source_refs': ['datapath'],
                                        'caveat': 'Nested predicates overlap across L1/L2/L3; do not '
                                                  'sum them into a stall partition.'},
            'backend/MEMSTALL_L3MISS': {'predicate': 'DelayN(no uops issued, 2) AND NOT lqEmpty AND '
                                                     'l1Miss AND l2Miss AND l3Miss',
                                        'unit': 'predicate cycles',
                                        'source_refs': ['datapath'],
                                        'caveat': 'Nested predicates overlap across L1/L2/L3; do not '
                                                  'sum them into a stall partition.'},
            'backend/IssueQueueAluCsrFenceDivMcfg_full': {'predicate': 'RegNext(issueQueue.io.enq.head.ready), '
                                                                       'selected integer issue queue',
                                                          'unit': 'predicate cycles',
                                                          'source_refs': ['scheduler'],
                                                          'caveat': 'Despite the _full event name, the '
                                                                    'source records ready, with no '
                                                                    'negation. The upstream '
                                                                    'ISSUE_GE_4_UOPS label is also '
                                                                    'inconsistent. Do not interpret '
                                                                    'this count as full cycles or >=4 '
                                                                    'issued uops.'},
            'backend/issueQueue_enq_fire_cnt': {'predicate': 'PopCount(RegNext(issueQueues.map(_.io.enq.map(_.fire)).flatten)), '
                                                             'scheduler instance selected by recorded '
                                                             'signal',
                                                'unit': 'scheduler enqueue events',
                                                'source_refs': ['scheduler', 'backend_order'],
                                                'caveat': 'Scheduler_1 is the FP scheduler in this '
                                                          'build; enqueues are not RVV issued/executed '
                                                          'uops. Upstream VF_UOPS_ISSUED does not '
                                                          'describe this predicate.'},
            'backend/rob_commitInstrLoad': {'predicate': 'ifCommitReg(PopCount(RegEnable(commitLoadVec, '
                                                         'isCommit)))',
                                            'unit': 'committed load-class instructions',
                                            'source_refs': ['rob_load'],
                                            'caveat': 'Not total cache transactions or memory bytes.'},
            'frontend/IBuffer_hungry': {'predicate': 'afterInit AND numValid == 0 AND NOT headBubble',
                                        'unit': 'predicate cycles',
                                        'source_refs': ['ibuffer']},
            'memblock/l1D_read_dcache_access': {'predicate': 'io.lsu.resp.fire AND NOT s2_is_prefetch',
                                                'unit': 'load response events',
                                                'source_refs': ['loadpipe']},
            'memblock/l1D_read_dcache_miss': {'predicate': 'io.lsu.resp.fire AND NOT s2_is_prefetch AND '
                                                           'real_miss',
                                              'unit': 'load miss response events',
                                              'source_refs': ['loadpipe']},
            'memblock/l1D_write_dcache_access': {'predicate': 's2_fire AND (s2_isStore OR (s2_isAMO AND '
                                                              'isWrite(cmd)))',
                                                 'unit': 'store/AMO pipeline events',
                                                 'source_refs': ['writepipe']},
            'memblock/l1D_write_dcache_miss': {'predicate': 's2_fire AND (s2_isStore OR (s2_isAMO AND '
                                                            'isWrite(cmd) AND NOT s2_hit))',
                                               'unit': 'source-predicate events',
                                               'source_refs': ['writepipe'],
                                               'caveat': 'Source parentheses apply !s2_hit only to the '
                                                         'AMO branch; all s2_isStore events count, '
                                                         'including hits. The aggregate must not be '
                                                         'used as a conventional L1 miss count/rate.'},
            'memblock/ldDeqCount': {'predicate': 'PopCount(issueLda.valid) + hybrid load valid count',
                                    'unit': 'load-address valid events',
                                    'source_refs': ['memblock'],
                                    'caveat': 'The source counts valid signals rather than downstream '
                                              'fire; this is not a retired instruction count or unique '
                                              'memory transaction count.'},
            'memblock/stDeqCount': {'predicate': 'PopCount(issueSta.valid) + hybrid store valid count',
                                    'unit': 'store-address valid events',
                                    'source_refs': ['memblock'],
                                    'caveat': 'The source counts valid signals rather than downstream '
                                              'fire; this is not a retired instruction count or unique '
                                              'memory transaction count.'},
            'memblock/replay_bank_conflict': {'predicate': 'PopCount(enq.fire AND NOT isLoadReplay AND '
                                                           'C_BC)',
                                              'unit': 'bank-conflict replay enqueue events',
                                              'source_refs': ['replay']},
            'memblock/stall_dcache': {'predicate': 's0_valid AND s0_can_go AND NOT dcache.req.ready',
                                      'unit': 'port-predicate cycles',
                                      'source_refs': ['ldu_stall'],
                                      'caveat': 'Summing ports yields port-cycles, potentially more '
                                                'than one per core cycle; not exclusive core stall '
                                                'time.'},
            'l2 cache/l2_cache_access_rd': {'predicate': 'task_s3.valid AND sinkA_req_s3 AND NOT '
                                                         'req_prefetch_s3',
                                            'unit': 'slice-local pipeline events',
                                            'source_refs': ['l2'],
                                            'caveat': 'Slice-local implementation predicates; names do '
                                                      'not establish DRAM requests/bytes. Refill '
                                                      'predicate depends on tl2tl/tl2chi path; a '
                                                      'conventional L2 miss ratio is not emitted.'},
            'l2 cache/l2_cache_miss_rd': {'predicate': 'task_s3.valid AND sinkA_req_s3 AND miss_s3',
                                          'unit': 'slice-local pipeline events',
                                          'source_refs': ['l2'],
                                          'caveat': 'Slice-local implementation predicates; names do '
                                                    'not establish DRAM requests/bytes. Refill '
                                                    'predicate depends on tl2tl/tl2chi path; a '
                                                    'conventional L2 miss ratio is not emitted.'},
            'l2 cache/l2_cache_refill': {'predicate': 'acquireUnit.io.sourceA.fire AND opcode == '
                                                      'AcquireBlock (tl2tl path)',
                                         'unit': 'slice-local pipeline events',
                                         'source_refs': ['l2_refill', 'default_config', 'chi_default'],
                                         'caveat': 'Slice-local implementation predicates; names do not '
                                                   'establish DRAM requests/bytes. Refill predicate '
                                                   'depends on tl2tl/tl2chi path; a conventional L2 '
                                                   'miss ratio is not emitted.'}},
 'coding': {'frontend/0': {'name': 'noEvent', 'signal': 'UInt<1>(0)'},
            'frontend/2': {'name': 'ifu_req', 'signal': 'NewIFU.io_perf[1].value: IO[UInt<6>]'},
            'frontend/3': {'name': 'ifu_miss', 'signal': 'NewIFU.io_perf[2].value: IO[UInt<6>]'},
            'frontend/15': {'name': 'IBuffer_hungry', 'signal': 'IBuffer.io_perf[1].value: IO[UInt<6>]'},
            'frontend/20': {'name': 'IBuffer_full', 'signal': 'IBuffer.io_perf[6].value: IO[UInt<6>]'},
            'frontend/28': {'name': 'mispredictRedirect', 'signal': 'Ftq.io_perf[3].value: IO[UInt<6>]'},
            'frontend/33': {'name': 'BpInstr', 'signal': 'Ftq.io_perf[8].value: IO[UInt<6>]'},
            'frontend/56': {'name': 'itlb_access', 'signal': 'TLB.io_perf[0].value: IO[UInt<6>]'},
            'frontend/57': {'name': 'itlb_miss', 'signal': 'TLB.io_perf[1].value: IO[UInt<6>]'},
            'backend/0': {'name': 'noEvent', 'signal': 'UInt<1>(0)'},
            'backend/55': {'name': 'rob_commitInstrLoad',
                           'signal': 'CtrlBlock.io_perf[54].value: IO[UInt<6>]'},
            'backend/67': {'name': 'EXEC_STALL_CYCLE',
                           'signal': 'DataPath.io_perf[0].value: IO[UInt<6>]'},
            'backend/68': {'name': 'MEMSTALL_STORE', 'signal': 'DataPath.io_perf[1].value: IO[UInt<6>]'},
            'backend/69': {'name': 'MEMSTALL_L1MISS',
                           'signal': 'DataPath.io_perf[2].value: IO[UInt<6>]'},
            'backend/70': {'name': 'MEMSTALL_L2MISS',
                           'signal': 'DataPath.io_perf[3].value: IO[UInt<6>]'},
            'backend/71': {'name': 'MEMSTALL_L3MISS',
                           'signal': 'DataPath.io_perf[4].value: IO[UInt<6>]'},
            'backend/76': {'name': 'IssueQueueAluCsrFenceDivMcfg_full',
                           'signal': 'Scheduler.io_perf[4].value: IO[UInt<6>]'},
            'backend/77': {'name': 'issueQueue_enq_fire_cnt',
                           'signal': 'Scheduler_1.io_perf[0].value: IO[UInt<6>]'},
            'memblock/0': {'name': 'noEvent', 'signal': 'UInt<1>(0)'},
            'memblock/3': {'name': 'stall_dcache', 'signal': 'LoadUnit.io_perf[2].value: IO[UInt<6>]'},
            'memblock/12': {'name': 'stall_dcache',
                            'signal': 'LoadUnit_1.io_perf[2].value: IO[UInt<6>]'},
            'memblock/21': {'name': 'stall_dcache',
                            'signal': 'LoadUnit_2.io_perf[2].value: IO[UInt<6>]'},
            'memblock/58': {'name': 'replay_bank_conflict',
                            'signal': 'LsqWrapper.io_perf[14].value: IO[UInt<6>]'},
            'memblock/85': {'name': 'l1D_write_dcache_access',
                            'signal': 'DCacheWrapper.io_perf[5].value: IO[UInt<6>]'},
            'memblock/86': {'name': 'l1D_write_dcache_miss',
                            'signal': 'DCacheWrapper.io_perf[6].value: IO[UInt<6>]'},
            'memblock/99': {'name': 'load_req',
                            'signal': 'DCacheWrapper.io_perf[19].value: IO[UInt<6>]'},
            'memblock/104': {'name': 'l1D_read_dcache_access',
                             'signal': 'DCacheWrapper.io_perf[24].value: IO[UInt<6>]'},
            'memblock/105': {'name': 'l1D_read_dcache_miss',
                             'signal': 'DCacheWrapper.io_perf[25].value: IO[UInt<6>]'},
            'memblock/106': {'name': 'load_req',
                             'signal': 'DCacheWrapper.io_perf[26].value: IO[UInt<6>]'},
            'memblock/111': {'name': 'l1D_read_dcache_access',
                             'signal': 'DCacheWrapper.io_perf[31].value: IO[UInt<6>]'},
            'memblock/112': {'name': 'l1D_read_dcache_miss',
                             'signal': 'DCacheWrapper.io_perf[32].value: IO[UInt<6>]'},
            'memblock/113': {'name': 'load_req',
                             'signal': 'DCacheWrapper.io_perf[33].value: IO[UInt<6>]'},
            'memblock/118': {'name': 'l1D_read_dcache_access',
                             'signal': 'DCacheWrapper.io_perf[38].value: IO[UInt<6>]'},
            'memblock/119': {'name': 'l1D_read_dcache_miss',
                             'signal': 'DCacheWrapper.io_perf[39].value: IO[UInt<6>]'},
            'memblock/121': {'name': 'dtlb_ld_miss',
                             'signal': 'TLBNonBlock.io_perf[1].value: IO[UInt<6>]'},
            'memblock/123': {'name': 'dtlb_st_miss',
                             'signal': 'TLBNonBlock_1.io_perf[1].value: IO[UInt<6>]'},
            'memblock/143': {'name': 'ldDeqCount',
                             'signal': 'MemBlockInlined.ldDeqCount: OpResult[UInt<3>]'},
            'memblock/144': {'name': 'stDeqCount',
                             'signal': 'MemBlockInlined.stDeqCount: OpResult[UInt<3>]'},
            'l2 cache/1': {'name': 'Slice0_l2_cache_refill',
                           'signal': 'TL2TLCoupledL2.io_perf[1].value: IO[UInt<6>]'},
            'l2 cache/14': {'name': 'Slice0_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[14].value: IO[UInt<6>]'},
            'l2 cache/16': {'name': 'Slice0_l2_cache_miss_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[16].value: IO[UInt<6>]'},
            'l2 cache/18': {'name': 'Slice1_l2_cache_refill',
                            'signal': 'TL2TLCoupledL2.io_perf[18].value: IO[UInt<6>]'},
            'l2 cache/31': {'name': 'Slice1_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[31].value: IO[UInt<6>]'},
            'l2 cache/33': {'name': 'Slice1_l2_cache_miss_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[33].value: IO[UInt<6>]'},
            'l2 cache/35': {'name': 'Slice2_l2_cache_refill',
                            'signal': 'TL2TLCoupledL2.io_perf[35].value: IO[UInt<6>]'},
            'l2 cache/48': {'name': 'Slice2_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[48].value: IO[UInt<6>]'},
            'l2 cache/50': {'name': 'Slice2_l2_cache_miss_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[50].value: IO[UInt<6>]'},
            'l2 cache/52': {'name': 'Slice3_l2_cache_refill',
                            'signal': 'TL2TLCoupledL2.io_perf[52].value: IO[UInt<6>]'},
            'l2 cache/65': {'name': 'Slice3_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[65].value: IO[UInt<6>]'},
            'l2 cache/67': {'name': 'Slice3_l2_cache_miss_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[67].value: IO[UInt<6>]'},
            'l2 cache/82': {'name': 'Slice4_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[82].value: IO[UInt<6>]'},
            'l2 cache/84': {'name': 'Slice4_l2_cache_miss_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[84].value: IO[UInt<6>]'},
            'l2 cache/99': {'name': 'Slice5_l2_cache_access_rd',
                            'signal': 'TL2TLCoupledL2.io_perf[99].value: IO[UInt<6>]'},
            'l2 cache/101': {'name': 'Slice5_l2_cache_miss_rd',
                             'signal': 'TL2TLCoupledL2.io_perf[101].value: IO[UInt<6>]'},
            'l2 cache/116': {'name': 'Slice6_l2_cache_access_rd',
                             'signal': 'TL2TLCoupledL2.io_perf[116].value: IO[UInt<6>]'},
            'l2 cache/118': {'name': 'Slice6_l2_cache_miss_rd',
                             'signal': 'TL2TLCoupledL2.io_perf[118].value: IO[UInt<6>]'},
            'l2 cache/133': {'name': 'Slice7_l2_cache_access_rd',
                             'signal': 'TL2TLCoupledL2.io_perf[133].value: IO[UInt<6>]'},
            'l2 cache/135': {'name': 'Slice7_l2_cache_miss_rd',
                             'signal': 'TL2TLCoupledL2.io_perf[135].value: IO[UInt<6>]'}}}

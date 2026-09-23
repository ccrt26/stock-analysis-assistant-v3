Traceback (most recent call last):
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 79, in perform
    result=fn();run.update(status='completed',result=result)
           ^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 153, in <lambda>
    for case in ('D1','H1','H2','H3'):perform('N-'+case,lambda c=case:handoff(c))
                                                                      ^^^^^^^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 96, in handoff
    if issues:raise ValueError('Historical meaning needs research resolution; no trial interpretation is invented: '+fio.dumps(issues))
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ValueError: Historical meaning needs research resolution; no trial interpretation is invented: [
  {
    "evidence": "input/packet.json#/authoring_note/text 含所引原句；#/facts/own/income_statement/0 的 report_period=\"2025-03-31\"、n_income_attr_p=11105273.05；#/facts/own/income_statement/1 的 report_period=\"2025-06-30\"、n_income_attr_p=25839190.76。两项 report_type 均为\"1\"、quality_status 均为\"passed\"，并记录相同 comparable_selection_rule=\"as_of_then_end_type_match_then_consolidated_report_then_available_at_then_statement_type\"。#/evidence/3/content 另有 h1_2026_net_income=45373264.4、q1_2026_net_income=31416835.81；#/unknowns 仍记“二季度单季同比、三季度利润及汇率影响是否逆转未确认”。原包 #/gaps 为空，未载这一差异的处理说明。",
    "needed": "由研究核对2025年一季度、半年与2026年对应归母净利润的合并范围、报表口径及是否追溯调整，确认是否确有不可比原因；若可比，由研究形成并记录单季同比及其对既有取舍的影响，若不可比则记录具体原因。本交接不计算或采用新同比，不改变原研究；作者仅保留“单季同比未确认”，不得自行补出加速、季节性或恢复论证。",
    "problem": "原便笺对单季同比未确认的原因写成“缺同口径上年一季度”，但原包已有上年一季度及半年结构化数据。现有记录未说明这些数据为何不可比，不能把“未完成可比性核对”写成“原包无该期数据”。这是未知项解释的核对问题；本次固定回放保留原推荐、风险接受理由及条件，不自行推导新的单季同比判断。",
    "quote": "这只说明二季度较一季度回落，缺同口径上年一季度，不补造单季同比、季节性或三季度恢复。",
    "ts_code": "300658.SZ"
  }
]


Traceback (most recent call last):
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 79, in perform
    result=fn();run.update(status='completed',result=result)
           ^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 144, in daily
    final,provider=p.complete(host,state,state_path,d,CFG,'astra','Historical upstream must already exist; no rescan permitted.',fallback=False)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$EXPERIMENT_ROOT/daily-root/tools/recommendation_pipeline.py", line 2852, in complete
    raise RuntimeError('本轮部分完成，保留成功一路产物，沿原身份恢复补缺失：' + detail)
RuntimeError: 本轮部分完成，保留成功一路产物，沿原身份恢复补缺失：推荐：ValueError: 同一问题同时给出已解决与未决：H-300658.SZ01

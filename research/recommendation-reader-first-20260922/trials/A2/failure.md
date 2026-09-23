Traceback (most recent call last):
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 79, in perform
    result=fn();run.update(status='completed',result=result)
           ^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 155, in <lambda>
    for i,arm in enumerate(('old','current','current','old'),1):perform(f'{group}{i}',lambda g=group,b=arm,i=i:author_trial(f'{g}{i}',g,b))
                                                                                                               ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 115, in author_trial
    return p.run_article_cycle(host,packet=effective,materials=m,directory=d,state=state,state_path=d/'state.json',config=CFG,provider='astra',fallback=False,allow_research_changes=False,expression_limit=0,clarification_limit=0,run_scope=trial,initial_author_spec=spec)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/recommendation_pipeline.py", line 1570, in run_article_cycle
    parsed = validator(article_stage(
                       ^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/recommendation_pipeline.py", line 1037, in article_stage
    return file_article_stage(host, state, state_path, directory, stage, config,
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/recommendation_pipeline.py", line 1166, in file_article_stage
    delivery, route = run_stage(host, state, state_path, directory, stage, spec['request'],
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/recommendation_pipeline.py", line 1840, in run_stage
    code, diag = host.run_agent(route, prompt_path, output, events, None, {**config, '_text_only': text_only, '_handoff_only': False})
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/research/recommendation-reader-first-20260922/scripts/run_trials.py", line 40, in counted
    result=actual_run(route,prompt,final,events,timeout,config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/stock_ai.py", line 1364, in run_agent
    return run_codex(prompt_path, final_path, jsonl_path, timeout_seconds, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$CANDIDATE_ROOT/tools/stock_ai.py", line 1306, in run_codex
    proc.communicate(prompt.encode("utf-8"), timeout=timeout_seconds)
  File "$USER_HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/subprocess.py", line 1201, in communicate
    self.wait()
  File "$USER_HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/subprocess.py", line 1264, in wait
    return self._wait(timeout=timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "$USER_HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/subprocess.py", line 2053, in _wait
    (pid, sts) = self._try_wait(0)
                 ^^^^^^^^^^^^^^^^^
  File "$USER_HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/lib/python3.12/subprocess.py", line 2011, in _try_wait
    (pid, sts) = os.waitpid(self.pid, wait_flags)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyboardInterrupt

# Implementation Plan — Enforce tool result budget per message

## Ordered Steps

1. **Add module constant** (pyccode.py top, next to `SUMMARY_HEAD_CHARS`)
   - `TOOL_RESULT_MESSAGE_BUDGET = 200_000`
   - Validation: `uv run python -c "import pyccode; print(pyccode.TOOL_RESULT_MESSAGE_BUDGET)"` prints 200000.

2. **Extract `_persist_tool_result` helper**
   - Move the body of `maybePersistLargeToolResult` (lines after the threshold check) into a new private function `_persist_tool_result(tool_use_id, output)`.
   - Rewrite `maybePersistLargeToolResult` to be a thin size-check wrapper that delegates.
   - Validation: existing per-result behavior unchanged.
     ```bash
     uv run python -c "
     import pyccode
     out = pyccode.maybePersistLargeToolResult('toolu_test', 'x' * 60000)
     assert len(out) <= 2300, f'expected ~2.2KB, got {len(out)}'
     assert pyccode.maybePersistLargeToolResult('toolu_test', 'x' * 100) == 'x' * 100
     print('per-result pass preserved')
     "
     ```

3. **Add `enforceToolResultBudget(results)` function**
   - Place next to `_persist_tool_result` / `maybePersistLargeToolResult`.
   - Implement per design.md: total → sort → greedy persist with skip heuristic.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     # Under budget: no-op
     small = [{'type':'tool_result','tool_use_id':f'id{i}','content':'x'*1000} for i in range(5)]
     assert pyccode.enforceToolResultBudget(small) is small or len(pyccode.enforceToolResultBudget(small)) == 5
     # Over budget via many medium results
     big = [{'type':'tool_result','tool_use_id':f'id{i}','content':'A'*30000} for i in range(10)]
     out = pyccode.enforceToolResultBudget(big)
     total = sum(len(r['content']) for r in out)
     assert total <= pyccode.TOOL_RESULT_MESSAGE_BUDGET, f'total {total} over budget'
     print(f'after enforce: {total} chars across {len(out)} results')
     "
     ```

4. **Wire into `chat()`**
   - After the `for content in response.content:` loop builds `results`,
     before `history.append({"role": "user", "content": results})`, insert:
     ```python
     results = enforceToolResultBudget(results)
     ```

5. **Wire into `handle_subagent()`**
   - Same insertion point, between building `results` and
     `messages.append({"role": "user", "content": results})`.

6. **Update spec**
   - `.trellis/spec/backend/chat-loop.md`: add a new section describing
     the two-layer persistence model (per-result then per-message).
   - Add `enforceToolResultBudget` to the function list in
     `.trellis/spec/backend/directory-structure.md` if appropriate.

## End-to-End Validation

After all steps:

```bash
# Sanity: import works
uv run python -c "import pyccode; print('ok')"

# Per-result pass still works (regression check)
uv run python -c "
import pyccode
out = pyccode.maybePersistLargeToolResult('toolu_r', 'x' * 60000)
print('per-result len:', len(out))
"

# Message-level budget enforcement
uv run python -c "
import pyccode
# 10 × 30KB = 300KB, no single one over 50K
rs = [{'type':'tool_result','tool_use_id':f'toolu_m{i}','content':'B'*30000} for i in range(10)]
out = pyccode.enforceToolResultBudget(rs)
total = sum(len(r['content']) for r in out)
print(f'in: 300000 chars, out: {total} chars, results: {len(out)}')
assert total <= pyccode.TOOL_RESULT_MESSAGE_BUDGET
persisted = sum(1 for r in out if r['content'].startswith('[tool_result_persisted]'))
print(f'persisted {persisted} of {len(out)}')
"

# Cleanup test artifacts
rm -rf $PWD/[0-9a-f]???????????????????????????????
```

## Review Gates

- After step 2: per-result regression test passes.
- After step 3: unit test of `enforceToolResultBudget` passes both
  under-budget (no-op) and over-budget (greedy shrink) cases.
- After step 5: end-to-end smoke test shows both passes compose correctly
  when run via the chat loop (or simulated).

## Rollback

Single-file change. `git checkout pyccode.py .trellis/spec/backend/chat-loop.md`
restores prior behavior. No data migration.

# Implementation Plan — Microcompact old tool results in history

## Ordered Steps

1. **Add module constants** (pyccode.py top, near other persistence constants)
   - `MICROCOMPACT_MAX_TOOL_RESULTS = 10`
   - `MICROCOMPACT_KEEP_RECENT = 5`
   - `COMPACTABLE_TOOLS = frozenset({"bash", "read", "write", "edit", "TodoWrite", "skill"})`
   - `OLD_TOOL_RESULT_PLACEHOLDER = "[Old tool result content cleared]"`
   - Validation: `uv run python -c "import pyccode; print(pyccode.MICROCOMPACT_MAX_TOOL_RESULTS, pyccode.COMPACTABLE_TOOLS)"`

2. **Add `microcompactMessages(history)` function**
   - Place near the other persistence helpers (after `enforceToolResultBudget`).
   - Implement per design.md: tool_use index → collect **uncleared compactable** locations → threshold check on uncleared count → compact older-than-recent.
   - Wrap whole body in `try/except Exception: return history` as safety net.
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     PL = pyccode.OLD_TOOL_RESULT_PLACEHOLDER

     # Under threshold: no-op
     h = [{'role':'user','content':[
         {'type':'tool_result','tool_use_id':f'id{i}','content':'x'*100} for i in range(5)
     ]}]
     pyccode.microcompactMessages(h)
     assert all(b['content'] == 'x'*100 for b in h[0]['content'])

     # Over threshold: clears oldest 7 of 12 uncleared compactable
     blocks = [{'type':'tool_result','tool_use_id':f'id{i}','content':f'output{i}'} for i in range(12)]
     h = [
         {'role':'assistant','content':[{'type':'tool_use','id':f'id{i}','name':'bash','input':{}} for i in range(12)]},
         {'role':'user','content':blocks},
     ]
     pyccode.microcompactMessages(h)
     cleared = sum(1 for b in h[1]['content'] if b['content'] == PL)
     intact = sum(1 for b in h[1]['content'] if b['content'].startswith('output'))
     print(f'cleared={cleared}, intact={intact}')
     assert cleared == 7 and intact == 5
     "
     ```

3. **Add uncleared-count + run_subagent exclusion tests**
   - Validation:
     ```bash
     uv run python -c "
     import pyccode
     PL = pyccode.OLD_TOOL_RESULT_PLACEHOLDER

     # Idempotency: re-running after compaction is a no-op (uncleared=5 <= 10)
     blocks = [{'type':'tool_result','tool_use_id':f'id{i}','content':f'output{i}'} for i in range(12)]
     h = [
         {'role':'assistant','content':[{'type':'tool_use','id':f'id{i}','name':'bash','input':{}} for i in range(12)]},
         {'role':'user','content':blocks},
     ]
     pyccode.microcompactMessages(h)
     snapshot = [b['content'] for b in h[1]['content']]
     pyccode.microcompactMessages(h)
     assert [b['content'] for b in h[1]['content']] == snapshot, 're-run must be no-op'

     # Add 5 more uncleared — total uncleared = 10, still no trigger
     for i in range(12, 17):
         h[0]['content'].append({'type':'tool_use','id':f'id{i}','name':'bash','input':{}})
         h[1]['content'].append({'type':'tool_result','tool_use_id':f'id{i}','content':f'output{i}'})
     pyccode.microcompactMessages(h)
     new_intact = sum(1 for b in h[1]['content'] if b['content'].startswith('output'))
     print(f'after 5 more added: intact={new_intact} (expected 10, uncleared=10 <= MAX)')
     assert new_intact == 10

     # Add 1 more — uncleared = 11 > MAX, triggers, clears oldest 6 uncleared
     h[0]['content'].append({'type':'tool_use','id':'id17','name':'bash','input':{}})
     h[1]['content'].append({'type':'tool_result','tool_use_id':'id17','content':'output17'})
     pyccode.microcompactMessages(h)
     final_intact = sum(1 for b in h[1]['content'] if b['content'].startswith('output'))
     print(f'after 1 more: intact={final_intact} (expected 5)')
     assert final_intact == 5

     # run_subagent never compacted
     sub_blocks = [{'type':'tool_result','tool_use_id':f'sub{i}','content':f'subout{i}'} for i in range(12)]
     h2 = [
         {'role':'assistant','content':[{'type':'tool_use','id':f'sub{i}','name':'run_subagent','input':{}} for i in range(12)]},
         {'role':'user','content':sub_blocks},
     ]
     pyccode.microcompactMessages(h2)
     sub_cleared = sum(1 for b in h2[1]['content'] if b['content'] == PL)
     print(f'subagent cleared={sub_cleared} (expected 0)')
     assert sub_cleared == 0
     "
     ```

4. **Wire into `chat()`**
   - Find the `while True:` loop, insert `microcompactMessages(history)` as the first statement before `client.messages.create(...)`.

5. **Wire into `handle_subagent()`**
   - Same insertion in the sub-agent's `while True:` loop.

6. **Update spec**
   - `.trellis/spec/backend/chat-loop.md`: add a new section "Layer 3 — `microcompactMessages`" describing the count-based cap, the COMPACTABLE_TOOLS exclusion, and the integration point.

## End-to-End Validation

```bash
# Sanity import
uv run python -c "import pyccode; print('ok')"

# Regression: existing layers still work
uv run python -c "
import pyccode
out = pyccode.maybePersistLargeToolResult('toolu_r', 'x' * 60000)
assert len(out) <= 2300
print('layer 1 ok')
"

# Full microcompact flow (uncleared-count trigger)
uv run python -c "
import pyccode
PL = pyccode.OLD_TOOL_RESULT_PLACEHOLDER

# 15 uncleared compactable: triggers, clears oldest 10 (keep recent 5)
blocks = [{'type':'tool_result','tool_use_id':f'id{i}','content':f'bash output {i}'} for i in range(15)]
h = [
    {'role':'assistant','content':[{'type':'tool_use','id':f'id{i}','name':'bash','input':{}} for i in range(15)]},
    {'role':'user','content':blocks},
]
pyccode.microcompactMessages(h)
cleared = sum(1 for b in h[1]['content'] if b['content'] == PL)
intact = sum(1 for b in h[1]['content'] if b['content'].startswith('bash'))
print(f'after 15 uncleared: cleared={cleared}, intact={intact}')
assert cleared == 10 and intact == 5

# Re-run: uncleared=5, no-op
snapshot = [b['content'] for b in h[1]['content']]
pyccode.microcompactMessages(h)
assert [b['content'] for b in h[1]['content']] == snapshot

# Mixed: 6 bash + 6 subagent = 12 total, but only 6 uncleared compactable → no trigger
blocks = []
tool_uses = []
for i in range(6):
    tool_uses.append({'type':'tool_use','id':f'b{i}','name':'bash','input':{}})
    blocks.append({'type':'tool_result','tool_use_id':f'b{i}','content':f'bash{i}'})
for i in range(6):
    tool_uses.append({'type':'tool_use','id':f's{i}','name':'run_subagent','input':{}})
    blocks.append({'type':'tool_result','tool_use_id':f's{i}','content':f'sub{i}'})
h2 = [{'role':'assistant','content':tool_uses}, {'role':'user','content':blocks}]
pyccode.microcompactMessages(h2)
cleared = sum(1 for b in h2[1]['content'] if b['content'] == PL)
print(f'mixed 6 bash + 6 subagent: cleared={cleared} (expected 0, uncleared compactable=6 <= MAX)')
assert cleared == 0
"
```

## Review Gates

- After step 2: unit tests pass (under-threshold no-op, over-threshold clears oldest 7).
- After step 3: run_subagent exclusion confirmed.
- After step 5: end-to-end smoke tests above pass.

## Rollback

Single-file change. `git checkout pyccode.py .trellis/spec/backend/chat-loop.md`
restores prior behavior. No data migration.

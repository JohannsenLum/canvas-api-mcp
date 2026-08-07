## What this changes

<!-- One or two sentences. Link the issue if there is one: Fixes #123 -->

## Why

<!-- What problem does this solve? If it adds a curated tool, say why the gateway
     (search_canvas_api + canvas_request) isn't sufficient — every curated tool costs
     context on every turn for every user. -->

## Checklist

- [ ] `uv run pytest` passes locally
- [ ] A test was added or updated, and it **fails without the change**
- [ ] No Canvas token, real course ID, or personal data appears in the diff
- [ ] Rate limiting in `client.py` is unchanged, or the change is explained above

<!-- Only if you touched tools -->

- [ ] Any write tool carries `destructiveHint=True`, `readOnlyHint=False`,
      `idempotentHint=False`
- [ ] Any write tool states its concrete effect in the **first sentence** of its
      description — that sentence is what the user sees in an approval prompt
- [ ] `README.md`'s tool table is updated

## Testing

<!-- How did you verify this? If you ran live tests against a real Canvas account,
     say which endpoints — but never paste responses containing real data. -->

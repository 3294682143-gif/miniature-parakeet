# Hard Mode Controlled Integration

## 1. Purpose
Provide an opt-in hard-mode policy layer for controlled strategy tuning without changing the stable default pipeline.

## 2. P12 Scope (Controlled CLI Hook v1)
- Hard Mode CLI is opt-in.
- Default CLI behavior is unchanged.
- P12 only attaches policy metadata / preview.
- P12 does not change solver behavior.
- P12 does not call external APIs by itself.
- P12 does not claim official accuracy.

## 3. Policy Levels
Supported levels are `off`, `light`, `standard`, and `strict`.

- `off`: baseline behavior profile.
- `light`: small candidate/verification increase.
- `standard`: stronger verification and trace requirement.
- `strict`: strongest policy with static hook flags for shadow eval/debugger follow-up.

## 4. Candidate Budget
- off: 1
- light: 2
- standard: 3
- strict: 5

## 5. Verifier Level
- off/light: `basic`
- standard: `strong`
- strict: `strict`

## 6. CLI Usage
默认（行为保持不变）：

```bash
python -m math_agent.cli solve \
  --question "计算 2+3" \
  --enable-tools \
  --mode fast \
  --no-trace
```

Hard-mode preview：

```bash
python -m math_agent.cli solve \
  --question "证明偶数加偶数仍为偶数" \
  --enable-tools \
  --mode fast \
  --no-trace \
  --hard-mode \
  --hard-mode-level standard
```

Strict preview：

```bash
python -m math_agent.cli solve \
  --question "证明题 mock" \
  --enable-tools \
  --mode fast \
  --no-trace \
  --hard-mode \
  --hard-mode-level strict
```

说明：strict 在 P12 仅为 metadata / policy preview，不代表 strict solver 已真实启用。

## 7. Safety Boundaries
- Hard Mode is opt-in.
- Default pipeline behavior is unchanged.
- This mode does not call external APIs by itself.
- This mode does not claim official accuracy.

# interns1-math-agent Agent Notes

- Default runtime mode is **mock**. Do not call any external API by default.
- Never hardcode or commit secrets/API keys.
- All solver outputs must be valid JSON and conform to `MathResult` schema.
- On failures, return schema-compliant JSON with `success=false` and populated `error`.

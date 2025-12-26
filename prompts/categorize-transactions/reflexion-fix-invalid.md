Prompt key: reflexion-fix-invalid

You previously attempted to categorize a transaction but provided an invalid category key that does not exist in the taxonomy.

**Transaction that needs recategorization:**
{{TRANSACTION_JSON}}

**Invalid category you provided:** `{{INVALID_CATEGORY}}`

**Valid categories from the taxonomy:**
{{VALID_CATEGORIES_LIST}}

Your task: Choose the correct category from the valid categories list above. You MUST use one of these exact category keys.

Respond with a single JSON object in this format:
```json
{
  "idx": {{IDX}},
  "category": "valid.category.key",
  "score": 0.85,
  "rationale": "Brief explanation of why this category fits"
}
```

Rules:
- Use ONLY categories from the valid list above
- Do not invent or modify category keys
- Match the category semantically to the transaction
- Keep rationale brief (1-2 sentences)

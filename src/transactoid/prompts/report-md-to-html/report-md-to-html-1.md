Convert the provided markdown report into a complete HTML document for email delivery.

Requirements:
- Output only HTML. Do not include markdown fences, JSON, or explanatory text.
- Return a full HTML document starting with `<!DOCTYPE html>`.
- Include `<html>`, `<head>`, and `<body>` tags.
- Preserve all report content, ordering, and section structure from markdown.
- Use semantic HTML elements where appropriate (`h1`-`h6`, `p`, `ul`, `ol`, `table`, `blockquote`, `code`, etc.).
- Keep styles minimal and inline-safe for email clients.
- Escape any unsafe content and produce valid HTML.

Markdown report input:
{{markdown_report}}

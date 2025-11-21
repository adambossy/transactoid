<!-- 677fb185-2505-402b-9adc-649c7a4b046e 567c0cce-9e4e-4ec6-a40c-abbae56a728c -->
# Implement Agent Loop in transactoid.py

## Overview

Implement the core agent loop in `run()` using OpenAI Agents SDK primitives. The loop will:

- Load and render the agent prompt template with database schema and taxonomy
- Create tool functions wrapped with `@function_tool` decorator
- Initialize an `Agent` with instructions and tools
- Use `Runner` to handle the ReAct loop with user input

## Implementation Steps

### 1. Add Dependencies and Imports

- Import OpenAI Agents SDK: `Agent`, `Runner`, `function_tool` from `openai.agents`
- Import services: `DB`, `Taxonomy` 
- Import path utilities for reading prompt template and schema file
- Import JSON for taxonomy serialization

### 2. Load and Render Prompt Template

- Read `prompts/agent_loop/<version>.md` file content using `promptorium.load_prompt("agent-loop")`
- Load database schema using `db.compact_schema_hint()`
- Load taxonomy from DB using `Taxonomy.from_db(db)` and serialize using `to_prompt()` method
- Replace `{{DATABASE_SCHEMA}}` and `{{CATEGORY_TAXONOMY}}` placeholders in template

### 3. Create Tool Functions

Create wrapper functions decorated with `@function_tool` for each tool:

- **`run_sql`**: Wraps `db.run_sql()` - takes SQL query as a  string, returns serialized results
- **`sync_transactions`**: Wraps sync tool - triggers Plaid sync (may need SyncTool instance)
- **`connect_new_account`**: Placeholder for Plaid connection flow
- **`update_category_for_transaction_groups`**: Wraps persist tool bulk recategorization
- **`tag_transactions`**: Wraps persist tool tagging functionality

Each tool should:

- Use proper type hints for SDK inference
- Return serializable results (dicts/lists, not ORM objects)
- Handle errors gracefully

### 4. Initialize Services

- Initialize `DB` instance (read from env vars: `TRANSACTOID_DATABASE_URL` or `DATABASE_URL`)
- Initialize `Taxonomy` from DB using `Taxonomy.from_db(db)`
- Initialize other required service instances (SyncTool, PersistTool if needed)

### 5. Create Agent and Runner

- Create `Agent` instance with:
- Name: "Transactoid"
- Instructions: rendered prompt template
- Tools: list of all tool functions
- Create `Runner` instance

### 6. Implement Interactive Loop

- Use `Runner.run_sync()` in a loop
- Read user input from stdin
- Handle exit conditions ("exit", "quit")
- Print agent responses using `result.final_output`
- Keep loop clean and concise using SDK primitives

## Files to Modify

- `agents/transactoid.py`: Main implementation
- Update `run()` function signature to accept optional DB/Taxonomy or initialize from env
- Add helper functions for prompt loading and rendering
- Add tool wrapper functions
- Implement the agent loop

## Key Design Decisions

1. **Service Initialization**: Initialize DB and Taxonomy from environment variables within `run()` to keep the function self-contained
2. **Tool Wrapping**: Use `@function_tool` decorator directly on wrapper functions rather than complex class-based tools
3. **Prompt Loading**: Read prompt template using `promptorium.load_prompt("agent-loop")` if available
4. **Taxonomy Format**: Use `Taxonomy.to_prompt()` to get structured dict, then serialize to readable format (YAML or formatted text)

## Notes

- The `batch_size` and `confidence_threshold` parameters in current signature may not be needed for the agent loop (they're for batch processing). Remove them.
- Tool implementations (SyncTool, PersistTool) are currently stubs - the agent loop will work with them as-is

### To-dos

- [ ] Add OpenAI Agents SDK imports and service imports to transactoid.py
- [ ] Create helper function to replace {{DATABASE_SCHEMA}} and {{CATEGORY_TAXONOMY}} placeholders
- [ ] Create tool wrapper functions with @function_tool decorator for all 5 tools
- [ ] Initialize DB and Taxonomy services using their public library interfaces
- [ ] Create Agent instance with rendered prompt and tools list
- [ ] Implement interactive loop using Runner.run_sync() with user input handling
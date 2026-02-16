# Agent Memory

This directory contains persistent knowledge for the Transactoid agent across sessions.
Core memory files are injected into the system prompt. Optional memory files are
 discoverable via a runtime tree hint and loaded on demand when relevant.

## Purpose

Agent memory enables:
- **Persistent knowledge**: Store patterns, rules, and domain-specific knowledge that survives sessions
- **Learned behavior**: Capture and reuse categorization rules, merchant mappings, and user preferences
- **Contextual reasoning**: Provide the agent with richer context for decision-making

## File Structure

- `README.md`: This file - memory purpose, conventions, and operating model
- `index.md`: Tree-based inventory of what currently exists in `memory/`
- `merchant-rules.md`: Merchant categorization rules mapping descriptors to taxonomy categories
- `budget.md`: Budget preferences and budgeting guidance template (optional, on-demand)
- `tax-returns/`: Local-only tax-return files (optional, on-demand)

## Loading Model

- **Core memory (always injected):** `index.md`, `merchant-rules.md`
- **Optional memory (discover + read on demand):** `budget.md`, `tax-returns/*`, and future optional files
- **Discovery source:** `index.md` provides a tree-style inventory and runtime tax-return file list

## Editing Conventions

Memory files are:
- **Human-readable markdown**: Designed for both agent and human consumption
- **Version controlled**: Tracked in git to preserve history and enable rollback
- **Directly editable**: Can be modified via built-in skills or manual edits
- **Prompt behavior varies by file class**:
  - Core files are always injected
  - Optional files are read only when the agent decides they are needed

### Shell-Based Editing

The agent can edit memory files using standard shell commands:
- `cat memory/merchant-rules.md` - Read current content
- `echo "content" >> memory/merchant-rules.md` - Append new content
- `sed -i 's/old/new/' memory/merchant-rules.md` - Replace content

Always validate changes after editing:
1. Check taxonomy keys are valid
2. Ensure format matches conventions
3. Confirm file is well-formed markdown

## Memory Limits

**V1 Implementation**: Core memory injection is unbounded; optional memory is on-demand.

Future versions may implement:
- Token budget tracking and memory truncation
- Priority-based memory loading
- Automatic summarization of old entries

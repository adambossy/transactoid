# Agent Memory

This directory contains persistent knowledge for the Transactoid agent across sessions. Memory files are injected into the system prompt so the agent can use accumulated context and learned patterns.

## Purpose

Agent memory enables:
- **Persistent knowledge**: Store patterns, rules, and domain-specific knowledge that survives sessions
- **Learned behavior**: Capture and reuse categorization rules, merchant mappings, and user preferences
- **Contextual reasoning**: Provide the agent with richer context for decision-making

## File Structure

- `index.md`: This file - describes memory purpose and conventions
- `merchant-rules.md`: Merchant categorization rules mapping descriptors to taxonomy categories

## Editing Conventions

Memory files are:
- **Human-readable markdown**: Designed for both agent and human consumption
- **Version controlled**: Tracked in git to preserve history and enable rollback
- **Directly editable**: Can be modified via built-in skills or manual edits
- **Prompt-injected**: Content is included in system prompts for agent awareness

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

**V1 Implementation**: No token budgeting or size caps. Memory injection is unbounded.

Future versions may implement:
- Token budget tracking and memory truncation
- Priority-based memory loading
- Automatic summarization of old entries

# Agent Skills

Agent skills extend Transactoid's capabilities through filesystem-based discovery. This document explains how skills work, how agents discover them, and how to create your own.

## Overview

Skills are directories containing a `SKILL.md` file with instructions for the agent. When a skill is relevant to a task, the agent reads the skill file and follows its instructions.

**Key features:**
- Always enabled (no feature flags)
- Discovered via filesystem navigation
- Three-tier precedence system (project > user > built-in)
- Provider-agnostic design (works with OpenAI, Gemini, and Claude)

## Skill Directories

Skills are discovered from three locations in precedence order:

### 1. Project Skills (`.claude/skills/`)
Project-specific skills checked into version control. These override user and built-in skills with the same name.

**Use for:**
- Domain-specific workflows
- Project conventions
- Team-shared skills

### 2. User Skills (`~/.claude/skills/`)
Personal skills shared across all projects on your machine.

**Use for:**
- Personal preferences
- Cross-project utilities
- Custom workflows

### 3. Built-in Skills (`src/transactoid/skills/`)
Skills shipped with Transactoid. Lowest precedence.

**Use for:**
- Common Transactoid operations
- Standard workflows
- Reference implementations

## Skill Structure

Each skill is a directory containing a `SKILL.md` file:

```
.claude/skills/
└── analyze-spending/
    └── SKILL.md
```

The `SKILL.md` file contains instructions in markdown format:

```markdown
# Analyze Monthly Spending

When the user asks to analyze spending for a specific month:

1. Query transactions for the target month using run_sql
2. Group by category and sum amounts
3. Calculate percentage of total spending per category
4. Present results as a formatted table
5. Highlight any unusual spending patterns

Example SQL:
```sql
SELECT
    category_key,
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount
FROM transactions
WHERE date >= '2024-01-01' AND date < '2024-02-01'
GROUP BY category_key
ORDER BY total_amount DESC;
```
```

## How Agents Discover Skills

### OpenAI and Gemini
These providers use filesystem navigation tools to discover skills:

1. Agent receives instructions listing skill directories
2. When relevant, agent uses read-only filesystem tools (ls, cat, grep) to explore skill directories
3. Agent reads `SKILL.md` files and applies instructions
4. Policy enforcement ensures read-only access limited to skill directories

**Filesystem tools available:**
- `pwd`, `ls`, `find` - Navigation
- `cat`, `head`, `tail` - Reading files
- `grep`, `rg` - Searching content
- `sed -n` - Extracting lines

**Safety constraints:**
- Read-only operations only
- Access restricted to configured skill directories
- Mutating commands blocked (rm, mv, cp, mkdir, etc.)
- Redirection operators blocked (>, >>, <<, <)

### Claude (Future)
Claude runtime will use native Claude Agent SDK skill support:

- Skills discovered from `.claude/skills` (project) and `~/.claude/skills` (user)
- Native SDK handles discovery and loading
- No filesystem tool emulation needed
- Built-in skills not part of Claude's native system

## Creating Skills

### 1. Choose a Location

- Project-specific → `.claude/skills/`
- Personal workflow → `~/.claude/skills/`
- Built-in reference → `src/transactoid/skills/`

### 2. Create Skill Directory

```bash
mkdir -p .claude/skills/my-skill
```

### 3. Write SKILL.md

Create clear, actionable instructions:

```markdown
# My Skill

Brief description of what this skill does.

## When to Use

Describe scenarios where this skill applies.

## Instructions

1. First step
2. Second step
3. Third step

## Example

Provide an example of the skill in action.
```

### 4. Test the Skill

Ask the agent to perform a task that should trigger the skill. The agent will:
1. Discover the skill directory
2. Read the SKILL.md file
3. Follow the instructions

## Skill Precedence

When multiple skills have the same name, precedence determines which is used:

```
Project (.claude/skills/analyze) ← Highest precedence
    ↓ overrides
User (~/.claude/skills/analyze)
    ↓ overrides
Built-in (src/transactoid/skills/analyze) ← Lowest precedence
```

To override a built-in skill:
1. Create a skill with the same directory name in `.claude/skills/` or `~/.claude/skills/`
2. The higher-precedence skill will be used

## Configuration

Customize skill directories via environment variables:

```bash
# Project skills (default: .claude/skills)
TRANSACTOID_AGENT_SKILLS_PROJECT_DIR=.claude/skills

# User skills (default: ~/.claude/skills)
TRANSACTOID_AGENT_SKILLS_USER_DIR=~/.claude/skills

# Built-in skills (default: src/transactoid/skills)
TRANSACTOID_AGENT_SKILLS_BUILTIN_DIR=src/transactoid/skills
```

## Troubleshooting

### Agent doesn't discover skills

**Check:**
1. Skill directory exists and is readable
2. `SKILL.md` file exists in skill directory
3. Environment variables point to correct locations (if customized)

**Debug:**
Ask the agent to "list files in .claude/skills" to verify filesystem access.

### Agent reads skill but doesn't follow instructions

**Common causes:**
1. Instructions too vague or ambiguous
2. Multiple conflicting instructions
3. Skill not relevant to current task

**Fix:**
- Make instructions more specific and actionable
- Add explicit "When to Use" section
- Provide concrete examples

### Permission errors with filesystem tools

**OpenAI/Gemini only:**

Filesystem tools are read-only and restricted to skill directories. If you see permission errors:
1. Verify the path is under a configured skill directory
2. Check that the directory exists and is readable
3. Ensure the command is in the allowlist (see "How Agents Discover Skills")

## Best Practices

### Writing Effective Skills

1. **Be specific**: Clear, step-by-step instructions work better than general guidance
2. **Include examples**: Show concrete examples of SQL queries, workflows, or outputs
3. **Define scope**: Explicitly state when the skill applies and when it doesn't
4. **Keep it focused**: One skill per well-defined task
5. **Use markdown formatting**: Make skills easy to scan with headings, lists, and code blocks

### Organizing Skills

1. **Group related skills**: Use subdirectories for skill categories
2. **Naming conventions**: Use descriptive, hyphenated names (e.g., `analyze-spending`, `sync-accounts`)
3. **Version control**: Check project skills into git for team collaboration
4. **Document dependencies**: Note if a skill requires specific tools or environment setup

### Testing Skills

1. **Test in isolation**: Create a minimal task that should trigger the skill
2. **Check discovery**: Ask agent to "show me the analyze-spending skill" to verify it can read the file
3. **Verify behavior**: Confirm agent follows instructions as expected
4. **Iterate**: Refine instructions based on agent's actual behavior

## Examples

### Example 1: Monthly Report Skill

**Location:** `.claude/skills/monthly-report/SKILL.md`

```markdown
# Monthly Financial Report

Generate a comprehensive monthly financial report.

## When to Use

When the user requests a monthly report, monthly summary, or asks to "analyze last month".

## Instructions

1. Determine target month (default to previous month if not specified)
2. Query transactions for the month using run_sql
3. Calculate totals by category
4. Identify top 5 merchants by spending
5. Compare to previous month (if data available)
6. Present as formatted report with sections:
   - Summary (total income, expenses, net)
   - Top categories
   - Top merchants
   - Month-over-month changes

## Example SQL

```sql
-- Transactions by category
SELECT
    category_key,
    COUNT(*) as count,
    SUM(amount) as total
FROM transactions
WHERE date >= :start_date AND date < :end_date
GROUP BY category_key
ORDER BY total DESC;

-- Top merchants
SELECT
    merchant_name,
    COUNT(*) as transaction_count,
    SUM(amount) as total_spent
FROM transactions
WHERE date >= :start_date AND date < :end_date
GROUP BY merchant_name
ORDER BY total_spent DESC
LIMIT 5;
```
```

### Example 2: Recategorize Tool Skill

**Location:** `~/.claude/skills/recategorize-merchant/SKILL.md`

```markdown
# Recategorize Merchant

Recategorize all transactions for a specific merchant.

## When to Use

When the user wants to change the category for all transactions from a merchant.

## Instructions

1. Ask user for merchant name if not specified
2. Look up merchant_id using run_sql
3. Ask user to confirm merchant (show sample transactions)
4. Ask for target category_key
5. Validate category exists in taxonomy
6. Use recategorize_merchant tool with merchant_id and category_key
7. Confirm success with count of updated transactions

## Important

- Always confirm merchant and category before recategorizing
- Show examples to prevent mistakes
- Validate category_key against taxonomy

## Example Query

```sql
SELECT merchant_id, merchant_name, COUNT(*) as transaction_count
FROM transactions
WHERE merchant_name LIKE :search_term
GROUP BY merchant_id, merchant_name;
```
```

## Reference

- [Agent Client Protocol](https://agentclientprotocol.com) - Protocol for agent communication
- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk) - SDK for Claude skills
- [Transactoid Core Runtime](../src/transactoid/core/runtime/README.md) - Runtime architecture

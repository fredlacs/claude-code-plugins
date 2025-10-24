---
name: plan
description: Multi-perspective task planner using 3 async workers with different reasoning styles (conservative, balanced, creative). Use when user requests planning, strategy, or breaking down complex/ambiguous tasks requiring architectural decisions, risk assessment, or exploring alternatives. Skip for simple single-step tasks or when user already provided detailed plan.
---

# Multi-Perspective Planning

Spawn 3 async workers to analyze tasks from complementary perspectives. You act as mediator to balance their viewpoints, weigh trade-offs, and synthesize a unified plan.

## Workflow

**1. Spawn Workers (parallel)**

```javascript
// Conservative Analyst (temp 0.3)
mcp__plugin_async-worker-manager_agent-manager__spawn_worker({
  description: "Risk analysis",
  prompt: "Analyze conservatively: risks, edge cases, dependencies, failure modes, mitigation. Task: [USER_TASK]",
  options: { temperature: 0.3 }
})

// Balanced Architect (temp 0.7)
mcp__plugin_async-worker-manager_agent-manager__spawn_worker({
  description: "Implementation plan",
  prompt: "Create structured plan: clear steps, file changes, testing strategy, best practices. Task: [USER_TASK]",
  options: { temperature: 0.7 }
})

// Creative Strategist (temp 1.0)
mcp__plugin_async-worker-manager_agent-manager__spawn_worker({
  description: "Alternative approaches",
  prompt: "Explore alternatives: innovative solutions, optimizations, future-proofing, novel patterns. Task: [USER_TASK]",
  options: { temperature: 1.0 }
})
```

**2. Wait & Read Results**

```javascript
mcp__plugin_async-worker-manager_agent-manager__wait()
// Read all 3 conversation history files
```

**3. Mediate & Synthesize**

YOU are the mediator. Analyze all 3 perspectives:
- Read each worker's output carefully
- Identify consensus points (all agree)
- Note disagreements and conflicting recommendations
- Balance trade-offs between conservative/balanced/creative views
- Weigh risks vs opportunities
- Choose optimal approach with clear rationale

Then create unified plan with:
- **Recommended Approach** (synthesized with reasoning)
- **Implementation Steps** (numbered, actionable)
- **Key Risks** (from conservative view)
- **Alternatives Considered** (from creative view)
- **Trade-offs Made** (how you balanced perspectives)

**4. User Approval**

Ask user to approve/modify before executing.

## Safeguards

- Replace `[USER_TASK]` with actual task description
- Verify all 3 workers completed before synthesis
- Flag worker disagreements prominently
- Never auto-execute without user approval

[See examples.md for detailed use cases](examples.md)

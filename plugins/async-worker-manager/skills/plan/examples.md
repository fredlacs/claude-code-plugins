# Planning Examples

## Basic Usage

**User**: "I need to add OAuth authentication to my Express API"

**Claude activates plan skill**:
1. Spawns 3 workers:
   - Conservative: Identifies risks (token storage, session management, CSRF)
   - Balanced: Plans steps (install passport, configure strategy, add routes, middleware)
   - Creative: Suggests alternatives (Auth0 vs custom, JWT vs sessions, refresh token patterns)

2. Synthesizes output:
   ```
   ## Recommended Plan: Passport.js with JWT

   ### Steps
   1. Install dependencies: passport, passport-google-oauth20, jsonwebtoken
   2. Configure OAuth credentials in environment variables
   3. Create auth routes (/auth/google, /auth/google/callback)
   4. Implement JWT generation on successful auth
   5. Add authentication middleware to protected routes

   ### Key Risks
   - Token storage: Use httpOnly cookies (prevent XSS)
   - CSRF protection: Add csrf token middleware
   - Session persistence: Redis for production scalability

   ### Alternatives Considered
   - Auth0 (faster but vendor lock-in)
   - Session-based auth (simpler but less scalable)

   ### Testing
   - Manual OAuth flow test
   - Automated tests for token validation
   ```

3. Asks: "Does this plan look good? I can start implementing, adjust the approach, or explore alternatives."

## Advanced Use Cases

### Refactoring Decisions

**User**: "Should we migrate from REST to GraphQL?"

Workers analyze:
- **Conservative**: Migration risks, learning curve, breaking changes, fallback strategy
- **Balanced**: Incremental migration path, coexistence strategy, timeline
- **Creative**: Hybrid approach, federation patterns, alternative API layers

Result: Data-driven decision with pros/cons and migration roadmap.

### Architectural Trade-offs

**User**: "Plan the architecture for a real-time collaboration feature"

Workers explore:
- **Conservative**: WebSocket reliability, connection handling, data consistency
- **Balanced**: Standard patterns (Socket.io, operational transforms, CRDT)
- **Creative**: Novel solutions (Yjs, Automerge, custom protocols)

Result: Comparison table of approaches with recommendation.

### Debug Strategy

**User**: "Our API is slow under load, plan how to investigate and fix"

Workers provide:
- **Conservative**: Root cause analysis (profiling, logging, metrics)
- **Balanced**: Standard fixes (caching, indexing, query optimization)
- **Creative**: Preventive patterns (circuit breakers, rate limiting, load shedding)

Result: Comprehensive debugging and optimization strategy.

## When NOT to Use

- Simple file edits: "Add a comment to this function" → Just do it
- Clear instructions: "Install lodash" → No planning needed
- User provided plan: "Follow these steps: 1, 2, 3..." → Execute directly
- Time-sensitive: "Fix this critical bug NOW" → Act immediately

## Meta Usage

The plan skill itself was designed using this same meta-planning approach! Three workers with different perspectives collaboratively designed the optimal skill structure.

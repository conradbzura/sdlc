---
name: role
description: >
  Author a review role. Use this skill whenever the user says "create a
  role", "add a review role", or "author a review role" (not a request to
  run a review under an existing role). Gathers the role's lens and blocking
  policy and, on approval, writes the role document to
  .sdlc/guides/role/<name>.md and maps its focus globs into guide-map.role
  in .sdlc/config.json.
subagent:
  support: optional
  type: general-purpose
  artifacts:
    - role_name
    - role_path
---

The key words MUST, MUST NOT, SHALL, SHALL NOT, SHOULD, SHOULD NOT, REQUIRED, RECOMMENDED, MAY, and OPTIONAL in this document are to be interpreted as described in RFC 2119.

# Role Skill

Author a reusable review role — a named lens (e.g. `architect`, `product-manager`) intended to be run by a review flow to produce findings. A role document declares only the reviewing perspective and the project-specific policy for what counts as blocking; the files a role's findings are scoped to are configured separately in `guide-map.role` (a glob-to-role map in `.sdlc/config.json`), exactly as `test` and `style` guides are mapped. This skill drafts the role document and the mapping entry interactively and, on approval, writes both. Review-time role selection is not yet wired — roles authored here are stored and discoverable for that forthcoming consumption.

## Pipeline Context

This skill authors a role for future consumption by a review flow — no review path selects a role today. It is invoked on demand, not as a fixed stage of the `issue → implement → test → commit → pr → review` pipeline. Roles authored here are discovered by name and exposed via the `sdlc_roles` tool and the `sdlc://guides/role/<name>` resource; their glob scope lives in `guide-map.role`.

## Implementation Notes

The role document is seeded from the bundled template appended to this skill's tool output (also available as the `sdlc://role-template` resource). The drafting loop is conversational: gather each part, render the full role document plus its `guide-map.role` entry, and obtain explicit approval before writing — there is no separate structured-planning interface for this skill.

## Invariants

- MUST seed the role document from the provided role-document template.
- The role document MUST contain the two body sections, with their exact headings: `## Lens / identity` and `## Blocking policy`. It MUST NOT embed glob patterns — scope lives in `guide-map.role`.
- MUST reject a `<name>` that is empty or contains path separators or `..` before drafting; the `sdlc_role` endpoint does not pre-validate the name, so this guard is the agent's responsibility.
- MUST NOT write either the role document or the config mapping until the user explicitly approves the draft of both.
- MUST write the approved role document to `.sdlc/guides/role/<name>.md`, creating the `.sdlc/guides/role/` directory if it does not exist.
- MUST map the role's focus globs under `guide-map.role` in `.sdlc/config.json` — a `{ "<glob>": ["<name>"] }` entry per glob, using `pathlib.PurePath.full_match` pattern syntax (the same matching as `test` and `style` guides). Create `.sdlc/config.json` (with a `guide-map.role` object) if it does not exist, and merge into any existing `guide-map` without disturbing other entries.
- MUST NOT proceed to any other pipeline step autonomously.

## Arguments

The MCP endpoint supplies the role `name` (the stem) appended below this skill prompt as `Target role: <name>`, along with the role-document template. The `name` determines the role document path `.sdlc/guides/role/<name>.md` and the stem used in its `guide-map.role` entries.

## Subagent Execution (Optional)

This skill MAY be executed in an isolated subagent to preserve parent context. When invoked with a `--subagent` flag, execute according to your tool:

**Claude Code:**
- MUST spawn a general-purpose subagent using the Agent tool with this brief:
  > You are executing the **`role`** skill from the SDLC pipeline tooling.
  > 1. Read the project instructions in `AGENTS.md`
  > 2. Read and execute the complete workflow defined in this skill's markdown
  > 3. Follow every step faithfully, especially the Invariants section
  > 4. Return a structured summary: key artifacts (`role_name`, `role_path`) and the `guide-map.role` globs mapped to the role

- The subagent drafts the role document and its mapping and returns them for approval; nothing is written until the user explicitly approves (the approval-gate Invariant applies inside the subagent — it MUST NOT write before approval). When the subagent returns, reproduce its full output to the user exactly as written so the user can give informed approval — do not summarize, condense, paraphrase, or omit sections, and do not repeat work or add your own commentary.

**Other LLM assistants:**
- Subagent execution may not be supported in your tool. Execute the skill inline following the normal workflow.

## Workflow

### Checklist

1. Resolve the target name and path
2. Establish the lens / identity
3. Define the blocking policy
4. Define the focus globs (the guide-map.role mapping)
5. Draft the role document and the mapping
6. Show the draft for approval
7. Write the role document and update the config
8. Return the paths

### 1. Resolve the target name and path

The target role name is supplied as `Target role: <name>`. The role document path is `.sdlc/guides/role/<name>.md`; its scope is mapped under `guide-map.role` in `.sdlc/config.json`.

- If a file already exists at the role document path, the user MUST be asked whether to overwrite it before proceeding.
- If `<name>` collides with a bundled role (e.g. `general-purpose`), warn the user that the authored file will shadow the bundled role for this project.
- If `<name>` is empty or contains path separators, reject it and ask the user for a valid stem.

### 2. Establish the lens / identity

Interview the user for the reviewing perspective this role embodies: what it evaluates, what expertise it simulates, and the kinds of findings it surfaces. Be concrete — an `architect` role evaluates module boundaries, coupling, and layering; a `product-manager` role evaluates whether the change serves the stated user need.

### 3. Define the blocking policy

Determine, with the user, which classes of finding this role treats as blocking versus advisory for this project. The default convention is that violations of MUST / SHALL guide rules are blocking and SHOULD / MAY observations are advisory; adapt it to the role and project.

### 4. Define the focus globs

Determine, with the user, the glob patterns that scope where this role's findings apply; these become `guide-map.role` entries mapping each glob to `<name>` in `.sdlc/config.json`. `**/*` covers the whole diff. If the user does not specify any, default to `**/*`. Patterns use `pathlib.PurePath.full_match` semantics (the same as `test` and `style` guide-map entries). Remind the user that the role MAY read any file for context but raises findings only within these globs.

### 5. Draft the role document and the mapping

Render the complete role document from the template (the two body sections, no embedded globs) and the `guide-map.role` mapping entries. The headings MUST match the template exactly. For a concrete example of a well-formed role, see the bundled `general-purpose` role (`sdlc://guides/role/general-purpose`).

### 6. Show the draft for approval

Present the full draft — name, the role document path and body, and the `guide-map.role` entries to be written to `.sdlc/config.json` — to the user. Nothing MUST be written until the user explicitly approves.

### 7. Write the role document and update the config

After approval:

- Create `.sdlc/guides/role/<name>.md` (creating `.sdlc/guides/role/` if needed) with the approved role document.
- Add the role's glob entries under `guide-map.role` in `.sdlc/config.json`, creating the file and the `guide-map` / `role` objects if absent and preserving any existing entries.

### 8. Return the paths

Print the written role document path and the `guide-map.role` entries added, and note that the role is now discoverable via `sdlc_roles()` and readable at `sdlc://guides/role/<name>`.

## Edge Cases

- **File already exists at the role document path:** Ask before overwriting; never silently clobber a user's role.
- **Name collides with a bundled role:** Warn that the user file shadows the bundled role for this project.
- **No focus globs provided:** Default to `**/*` (whole diff) rather than writing an empty list.
- **`.sdlc/config.json` already has a `guide-map`:** Merge the role's entries into `guide-map.role`, preserving existing `test` / `style` / `role` entries; do not overwrite the file wholesale.
- **Invalid name (path separators, empty):** Reject and ask the user for a valid stem.

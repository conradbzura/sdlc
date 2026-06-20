---
name: <name>
---

# Role: <name>

Key words MUST, MUST NOT, SHOULD, and SHOULD NOT are interpreted as described in RFC 2119.

This template defines the required structure of a review-role document. A role document MUST contain the two body sections below, with these exact headings. A role declares only its reviewing perspective here; the files its findings are scoped to are configured separately in `guide-map.role` (a glob-to-role map in `.sdlc/config.json`), the same way `test` and `style` guides are mapped.

## Lens / identity

Describe the reviewing perspective this role embodies: what it cares about, what expertise it simulates, and the kinds of findings it surfaces. Be specific — an `architect` role evaluates module boundaries, coupling, and layering; a `product-manager` role evaluates whether the change serves the stated user need.

## Blocking policy

State which finding classes this role treats as blocking versus advisory, for this project. The default convention is that violations of MUST / SHALL guide rules are blocking and SHOULD / MAY observations are advisory; adapt it to the role and the project.

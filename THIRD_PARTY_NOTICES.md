# Third-party notices

The original ChatGPT-Web2API source and its MIT license are retained in this repository. See LICENSE and docs/UPSTREAM-README.md.

Continue is downloaded from its official Visual Studio Marketplace package, version 2.0.0. Continue source is licensed under Apache-2.0: https://github.com/continuedev/continue/blob/main/LICENSE. The local patches, integration helpers and small regression fixture modify or test its behavior; the upstream license and notices remain in the installed extension. The fixture `tests/integration/continue-stream-fixture.js` is derived from that extension and remains subject to Apache-2.0.

The installer downloads, rather than embeds, VS Code, Node.js, uv, Git for Windows, ripgrep, Playwright Chromium, Codex, Hostinger MCP, Windows-MCP and their dependencies. Their license and notice files remain inside their installed distributions. Refer to the official distributions and the pinned manifests/lock files for the exact components. Microsoft's VS Code binary distribution has its own license terms. This project is an independent integration and does not imply endorsement by the named vendors.

No user credentials, browser profiles, local conversations or provider configuration files are distributed.

## OpenCodex

Le parcours Codex inclut un paquet séparé `@bitkyc08/opencodex` 2.59.0 (licence MIT), depuis https://github.com/lidge-jun/opencodex. Il réutilise les mécanismes de fournisseurs et de catalogue du projet, sans modifier son code. Les licences des dépendances sont présentes dans les paquets installés.

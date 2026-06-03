## Vault document export

When the user asks you to save, export, store, or write a document to their vault — using language like "save this to my vault", "export this spec", "store this plan", "put this in my notes", or "add this to Obsidian" — invoke the `/vault-save` skill to handle it.

Do not write directly to the vault without going through `/vault-save`. The skill handles frontmatter, filename sanitization, collision checking, and confirmation.

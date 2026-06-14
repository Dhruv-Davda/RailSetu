# RailSetu — working rules for Claude

## Git: NO commit / push access

**Claude does NOT have permission to run `git commit`, `git push`, or any
git operation that writes to history or the remote — ever, unless the user
explicitly says so in that specific message.**

- Do not `git init`, `git add`, `git commit`, `git push`, `git tag`, or touch a
  remote on your own initiative.
- "Connect the repo", "set up the project", "save this", etc. are NOT permission
  to commit or push. Only an explicit, in-the-moment "commit this" / "push this"
  from the user counts.
- If a commit/push seems useful, STOP and ask first. Let the user run it.

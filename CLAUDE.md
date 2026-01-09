## Important agent instructions on documentation

- Each new module should have its own DOCUMENTATION.md file, explaining how it works.
- All the gameplay elements and game content should be described in WIKI.md. Both the user and the agent after careful reading of this file should understand ALL the features of the codebase. See this as a through executive summary.
- All the progress should be documented in the file PROGRESS.md. After finishing each feature, the PROGRESS.md file should be updated, so if a user or an agent reads through this file, he should understand what this file is about.
- If the file PROGRESS.md is not created, but the code is already there, the file PROGRESS.md should be created with all the features explained and marked as working/planned, in accordance to the existing documentation.

## Important agent instructions about git usage

- Each feature that should be added, should be added in a separate git branch.
- The naming of the branch should have the following schema: <type_of_branch>/<feature_name>. For example: feature/async_judging
- Types of branches can be: feature, refactor, bugfix and methodology. feature branches add completely new features, refactor branches refactor and/or simplify the code, bugfix are for fixing bugs and methodology branches are for changing methodology of the experiments.
- Each meaningful code change should be formalized into a commit. This change may span multiple files and functions, but it should contain only one TODO item.
- Commit names follow the schema: <type_of_commit>: <description_of_commit>. For example: feat: Added asynchronous querying of the API for the judging
- Types of commits can be: feat, refactor, fix. feat commits are the commits that add new features, refactor are for refactoring of the code without any changes, fix are for bugfixes.
- Unit tests should be added after each branch merge.
- After the feature is finished and tested, the agent should ask whether the branch should be merged into main. If the user agrees, the agent should merge.
- Branches should never break main -- if feature A breaks the main branch, it should not be merged.


## Most important agent instructions on general productivity

- Each TODO list item MUST be committed right after it was checked as completed. Refer to the git usage instructions for commit message format.
- NEVER commit the changes from TODOs in bulk -- only commit them RIGHT AFTER the TODO is checked as completed. This is needed to have TODO lists appear in the commit history, so be sure to strictly follow this rule
- Before merging, the code should be ran through linter and formatter. If any problems arise, they should be fixed before merging.
- Graphics should be done only after 

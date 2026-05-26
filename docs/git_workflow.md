# Git and Pull Request Workflow Guide

This document establishes the standardized Git and Pull Request (PR) workflow for the `simple-elt` project, incorporating both standard git commands and the GitHub CLI (`gh`) for seamless terminal orchestration.

---

## 🚀 Step 1: Create a Feature Branch

Always create a descriptive, short-scoped feature branch off the latest `main` branch.

```bash
# 1. Fetch latest remote state
git checkout main
git pull origin main

# 2. Spin up the feature branch
git checkout -b <branch_type>/<branch_desc>
```
*Example branch names:*
- `fix/parameter-edge-cases-and-restructure`
- `feat/added-schema-validation`

---

## 🛠️ Step 2: Stage and Commit Changes

Write clean, modular commits adhering to Conventional Commits standards.

```bash
# 1. Inspect uncommitted files
git status

# 2. Stage changes (use descriptive additions)
git add .

# 3. Create a structured commit
git commit -m "<type>(<scope>): <short description>"
```
*Common Conventional types:*
- `feat`: New feature additions.
- `fix`: Bug corrections.
- `test`: Suite additions or refactoring.
- `docs`: Documentation updates.

---

## 📤 Step 3: Push Branch to Origin

Push your local branch to the remote repository.

```bash
# Push and set upstream tracking for the new branch
git push -u origin <branch_name>
```

---

## 📝 Step 4: Create a Pull Request (PR)

Create a clean, descriptive PR using the standard GitHub Web UI or the GitHub CLI (`gh`) directly from your terminal.

```bash
# Create the PR interactively via GitHub CLI
gh pr create --title "<type>(<scope>): <summary>" --body-file "<path_to_pr_body_txt>"
```

---

## 🔍 Step 5: Reviewing the Pull Request

Verify PR metrics, check statuses, and review code differences.

```bash
# 1. View general status of current branch PR
gh pr status

# 2. Review code diffs directly in terminal
gh pr diff

# 3. Review comments or checks
gh pr view --web
```

---

## 🔄 Step 6: Rebasing the Pull Request

Rebasing ensures a clean, linear commit history by re-applying feature branch commits on top of the latest `main`.

If `main` has moved forward since you created your branch:

```bash
# 1. Update your local main tracking branch
git checkout main
git pull origin main

# 2. Switch back to your feature branch
git checkout <branch_name>

# 3. Rebase your feature branch commits onto the latest main
git rebase main

# 4. If conflicts arise, resolve them, then stage and continue:
# git add <resolved_files>
# git rebase --continue

# 5. Push the rebased commits (requires force-with-lease for safety)
git push --force-with-lease
```

---

## 🤝 Step 7: Merging the Pull Request

Once reviews are complete and all CI/CD integration tests pass:

```bash
# Merge the PR using GitHub CLI (rebase merge is recommended for linear logs)
gh pr merge --rebase
```

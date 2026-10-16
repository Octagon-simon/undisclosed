# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ========= Copyright 2025-2026 @ Eigent.ai All Rights Reserved. =========

"""GitHub REST toolkit (backed by PyGithub).

Extends camel's ``GithubToolkit`` (reads + create-PR) with the issue and PR
management operations the developer agent needs day to day: create / update /
close / reopen issues, comment on issues and PRs, merge / close pull requests,
create and list branches, enumerate repositories, and search issues.

Enabled only when ``GITHUB_ACCESS_TOKEN`` is set; ``get_can_use_tools`` returns
``[]`` otherwise, so the agent stays GitHub-free until a token is configured.
PyGithub is imported lazily by the base class, so this module imports cleanly
even when the package is not installed.
"""

import logging

from camel.toolkits import GithubToolkit as BaseGithubToolkit
from camel.toolkits.function_tool import FunctionTool

from app.agent.toolkit.abstract_toolkit import AbstractToolkit
from app.component.environment import env
from app.service.task import Agents
from app.utils.listen.toolkit_listen import auto_listen_toolkit

logger = logging.getLogger("github_toolkit")

_VALID_MERGE_METHODS = {"merge", "squash", "rebase"}
_VALID_ISSUE_STATES = {"open", "closed"}

#: Tools that mutate GitHub state (create/update/close/comment/merge). The
#: single-agent assembler gates these under Ask mode, mirroring
#: ``git_toolkit.WRITE_TOOL_NAMES`` for local git. Reads (github_get_*,
#: github_list_*, github_search_issues) stay ungated.
WRITE_TOOL_NAMES = {
    "github_create_pull_request",
    "github_create_pull_request_from_branch",
    "github_merge_pull_request",
    "github_close_pull_request",
    "github_add_pull_request_comment",
    "github_create_issue",
    "github_update_issue",
    "github_close_issue",
    "github_reopen_issue",
    "github_add_issue_comment",
    "github_create_branch",
}


@auto_listen_toolkit(BaseGithubToolkit)
class GithubToolkit(BaseGithubToolkit, AbstractToolkit):
    agent_name: str = Agents.developer_agent

    def __init__(
        self,
        api_task_id: str,
        access_token: str | None = None,
        timeout: float | None = None,
    ) -> None:
        super().__init__(access_token, timeout)
        self.api_task_id = api_task_id

    @classmethod
    def get_can_use_tools(cls, api_task_id: str) -> list[FunctionTool]:
        # Pass the token through explicitly rather than letting the base class
        # re-read os.environ: the gate below resolves the token through the app
        # env loader (which also reads `.env` files live), but the base
        # `get_github_access_token` only reads os.environ. Passing it keeps the
        # two in agreement and avoids a spurious "missing token" raise when the
        # token came from a dotenv file.
        token = env("GITHUB_ACCESS_TOKEN")
        if token:
            return GithubToolkit(api_task_id, access_token=token).get_tools()
        return []

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _describe_error(exc: Exception) -> str:
        """Render a PyGithub/API exception as a short, readable string."""
        status = getattr(exc, "status", None)
        data = getattr(exc, "data", None)
        if data:
            message = data.get("message") if isinstance(data, dict) else data
            return f"[github error]: {status}: {message}"
        return f"[github error]: {exc}"

    def _repo(self, repo_name: str):
        """Resolve an ``owner/repo`` slug to a PyGithub Repository object."""
        return self.github.get_repo(repo_name)

    # ------------------------------------------------------------------ #
    # Issue management
    # ------------------------------------------------------------------ #

    def github_create_issue(
        self,
        repo_name: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> str:
        """Create a new issue in a repository.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            title (str): Issue title (required, must be non-empty).
            body (str): Markdown body of the issue.
            labels (list[str], optional): Label names to apply.
            assignees (list[str], optional): GitHub usernames to assign.

        Returns:
            str: Confirmation with the new issue number and URL, or an error.
        """
        if not title or not title.strip():
            return "[github error]: an issue title is required."
        try:
            repo = self._repo(repo_name)
            issue = repo.create_issue(
                title=title.strip(),
                body=body or "",
                labels=labels or [],
                assignees=assignees or [],
            )
            return (
                f"Created issue #{issue.number}: {issue.title}\n"
                f"{issue.html_url}"
            )
        except Exception as exc:
            return self._describe_error(exc)

    def github_update_issue(
        self,
        repo_name: str,
        issue_number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> str:
        """Edit an existing issue's fields.

        Only the fields you pass are changed; omitted fields are left as-is.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            issue_number (int): The issue number to edit.
            title (str, optional): New title.
            body (str, optional): New body.
            state (str, optional): ``open`` or ``closed``.
            labels (list[str], optional): Replacement label set (pass ``[]``
                to clear all labels).
            assignees (list[str], optional): Replacement assignee list (pass
                ``[]`` to clear all assignees).

        Returns:
            str: Confirmation or an error.
        """
        if state is not None and state not in _VALID_ISSUE_STATES:
            return "[github error]: state must be 'open' or 'closed'."
        fields: dict[str, object] = {}
        if title is not None:
            fields["title"] = title
        if body is not None:
            fields["body"] = body
        if state is not None:
            fields["state"] = state
        if labels is not None:
            fields["labels"] = labels
        if assignees is not None:
            fields["assignees"] = assignees
        if not fields:
            return (
                "[github error]: nothing to update; pass at least one field."
            )
        try:
            issue = self._repo(repo_name).get_issue(int(issue_number))
            issue.edit(**fields)
            return (
                f"Updated issue #{issue.number} ({issue.state}): "
                f"{issue.title}\n{issue.html_url}"
            )
        except Exception as exc:
            return self._describe_error(exc)

    def github_close_issue(
        self, repo_name: str, issue_number: int, comment: str = ""
    ) -> str:
        """Close an issue, optionally leaving a comment first.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            issue_number (int): The issue number to close.
            comment (str): Optional comment posted before closing.

        Returns:
            str: Confirmation or an error.
        """
        try:
            issue = self._repo(repo_name).get_issue(int(issue_number))
            if comment and comment.strip():
                issue.create_comment(comment.strip())
            issue.edit(state="closed")
            return f"Closed issue #{issue.number}: {issue.title}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_reopen_issue(
        self, repo_name: str, issue_number: int, comment: str = ""
    ) -> str:
        """Reopen a previously closed issue.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            issue_number (int): The issue number to reopen.
            comment (str): Optional comment posted before reopening.

        Returns:
            str: Confirmation or an error.
        """
        try:
            issue = self._repo(repo_name).get_issue(int(issue_number))
            if comment and comment.strip():
                issue.create_comment(comment.strip())
            issue.edit(state="open")
            return f"Reopened issue #{issue.number}: {issue.title}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_add_issue_comment(
        self, repo_name: str, issue_number: int, comment: str
    ) -> str:
        """Add a comment to an issue (or a pull request's timeline).

        Args:
            repo_name (str): Repository as ``owner/repo``.
            issue_number (int): The issue number to comment on.
            comment (str): The comment text (required).

        Returns:
            str: Confirmation with the comment URL, or an error.
        """
        if not comment or not comment.strip():
            return "[github error]: comment text is required."
        try:
            issue = self._repo(repo_name).get_issue(int(issue_number))
            created = issue.create_comment(comment.strip())
            return f"Commented on #{issue.number}. {created.html_url}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_get_issue_comments(
        self, repo_name: str, issue_number: int, limit: int = 30
    ) -> str:
        """List the comments on an issue.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            issue_number (int): The issue number.
            limit (int): Maximum number of comments to return (default 30).

        Returns:
            str: A formatted list of ``@user (date): body`` entries, or an
            error.
        """
        try:
            issue = self._repo(repo_name).get_issue(int(issue_number))
            lines: list[str] = []
            for i, c in enumerate(issue.get_comments()):
                if i >= limit:
                    lines.append("... (truncated)")
                    break
                lines.append(
                    f"- @{c.user.login} ({c.created_at:%Y-%m-%d}): {c.body}"
                )
            if not lines:
                return f"Issue #{issue.number} has no comments."
            return f"Comments on #{issue.number}:\n" + "\n".join(lines)
        except Exception as exc:
            return self._describe_error(exc)

    def github_search_issues(
        self, query: str, repo_name: str = "", limit: int = 20
    ) -> str:
        """Search issues and pull requests across GitHub.

        Args:
            query (str): GitHub search syntax, e.g. ``is:open label:bug``.
            repo_name (str): Optional ``owner/repo`` to scope the search.
            limit (int): Maximum number of results to return (default 20).

        Returns:
            str: A formatted list of matches, or an error.
        """
        if not query or not query.strip():
            return "[github error]: a search query is required."
        q = query.strip()
        if repo_name:
            q += f" repo:{repo_name}"
        try:
            results = self.github.search_issues(query=q)
            lines: list[str] = []
            for i, item in enumerate(results):
                if i >= limit:
                    lines.append("... (truncated)")
                    break
                kind = "PR" if item.pull_request else "issue"
                lines.append(
                    f"- [{kind}] #{item.number} {item.title} "
                    f"({item.state}) {item.html_url}"
                )
            if not lines:
                return f"No results for '{q}'."
            return f"Results for '{q}':\n" + "\n".join(lines)
        except Exception as exc:
            return self._describe_error(exc)

    # ------------------------------------------------------------------ #
    # Pull request management
    # ------------------------------------------------------------------ #

    def github_merge_pull_request(
        self,
        repo_name: str,
        pr_number: int,
        commit_message: str = "",
        merge_method: str = "merge",
    ) -> str:
        """Merge a pull request.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            pr_number (int): The pull request number to merge.
            commit_message (str): Optional merge commit message.
            merge_method (str): One of ``merge`` (default), ``squash`` or
                ``rebase``.

        Returns:
            str: Confirmation or an error.
        """
        if merge_method not in _VALID_MERGE_METHODS:
            return (
                "[github error]: merge_method must be one of merge, squash, "
                "rebase."
            )
        try:
            pr = self._repo(repo_name).get_pull(int(pr_number))
            result = pr.merge(
                commit_message=commit_message or "",
                merge_method=merge_method,
            )
            if result.merged:
                return f"Merged PR #{pr.number}: {result.message}"
            return f"Could not merge PR #{pr.number}: {result.message}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_close_pull_request(
        self, repo_name: str, pr_number: int, comment: str = ""
    ) -> str:
        """Close a pull request without merging, optionally commenting first.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            pr_number (int): The pull request number to close.
            comment (str): Optional comment posted before closing.

        Returns:
            str: Confirmation or an error.
        """
        try:
            pr = self._repo(repo_name).get_pull(int(pr_number))
            if comment and comment.strip():
                pr.create_issue_comment(comment.strip())
            pr.edit(state="closed")
            return f"Closed PR #{pr.number}: {pr.title}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_add_pull_request_comment(
        self, repo_name: str, pr_number: int, comment: str
    ) -> str:
        """Add a general (timeline) comment to a pull request.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            pr_number (int): The pull request number.
            comment (str): The comment text (required).

        Returns:
            str: Confirmation with the comment URL, or an error.
        """
        if not comment or not comment.strip():
            return "[github error]: comment text is required."
        try:
            pr = self._repo(repo_name).get_pull(int(pr_number))
            created = pr.create_issue_comment(comment.strip())
            return f"Commented on PR #{pr.number}. {created.html_url}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_create_pull_request_from_branch(
        self,
        repo_name: str,
        head: str,
        title: str,
        base: str = "",
        body: str = "",
        draft: bool = False,
    ) -> str:
        """Open a pull request from an existing (already-pushed) branch.

        Unlike ``github_create_pull_request`` (which rewrites a single file
        off the default branch), this opens a PR for whatever commits already
        sit on ``head``. Use this when the work lives on a feature branch.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            head (str): Branch the PR is opened from; it must already exist
                on the remote (push it first, e.g. with ``git_push``).
            title (str): Pull request title (required).
            base (str): Target branch; empty means the repo's default branch.
            body (str): Pull request description.
            draft (bool): Open as a draft PR (default False).

        Returns:
            str: Confirmation with the PR number and URL, or an error.
        """
        if not head or not head.strip():
            return "[github error]: head branch is required."
        if not title or not title.strip():
            return "[github error]: a pull request title is required."
        try:
            repo = self._repo(repo_name)
            pr = repo.create_pull(
                title=title.strip(),
                body=body or "",
                head=head.strip(),
                base=base.strip() or repo.default_branch,
                draft=draft,
            )
            return f"Opened PR #{pr.number}: {pr.title}\n{pr.html_url}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_get_pull_request(self, repo_name: str, pr_number: int) -> str:
        """Show a pull request's state, branches and mergeability.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            pr_number (int): The pull request number.

        Returns:
            str: A short summary of the PR, or an error.
        """
        try:
            pr = self._repo(repo_name).get_pull(int(pr_number))
            state = "merged" if pr.merged else pr.state
            return (
                f"PR #{pr.number}: {pr.title}\n"
                f"  {pr.head.ref} -> {pr.base.ref}\n"
                f"  state: {state}, draft: {pr.draft}, "
                f"mergeable: {pr.mergeable}\n"
                f"  {pr.html_url}"
            )
        except Exception as exc:
            return self._describe_error(exc)

    # ------------------------------------------------------------------ #
    # Repository / branch helpers
    # ------------------------------------------------------------------ #

    def github_create_branch(
        self, repo_name: str, branch_name: str, from_ref: str = ""
    ) -> str:
        """Create a new branch, by default from the repo's default branch.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            branch_name (str): Name of the new branch (required).
            from_ref (str): Branch/ref/SHA to branch from; empty means the
                repository's default branch.

        Returns:
            str: Confirmation with the new branch tip, or an error.
        """
        if not branch_name or not branch_name.strip():
            return "[github error]: a branch name is required."
        name = branch_name.strip()
        try:
            repo = self._repo(repo_name)
            base = from_ref.strip() or repo.default_branch
            sha = repo.get_branch(base).commit.sha
            ref = repo.create_git_ref(ref=f"refs/heads/{name}", sha=sha)
            return (
                f"Created branch '{name}' from '{base}' "
                f"({ref.object.sha[:7]})."
            )
        except Exception as exc:
            return self._describe_error(exc)

    def github_list_branches(self, repo_name: str, limit: int = 100) -> str:
        """List a repository's branches.

        Args:
            repo_name (str): Repository as ``owner/repo``.
            limit (int): Maximum number of branches to return (default 100).

        Returns:
            str: A formatted list of branch names, or an error.
        """
        try:
            repo = self._repo(repo_name)
            names: list[str] = []
            for i, branch in enumerate(repo.get_branches()):
                if i >= limit:
                    names.append("... (truncated)")
                    break
                names.append(branch.name)
            body = "\n".join(f"- {n}" for n in names) or "(none)"
            return f"Branches in {repo_name}:\n{body}"
        except Exception as exc:
            return self._describe_error(exc)

    def github_list_repositories(self, limit: int = 50) -> str:
        """List repositories the configured token can access.

        Args:
            limit (int): Maximum number of repositories to return
                (default 50).

        Returns:
            str: A formatted list of ``owner/repo`` slugs, or an error.
        """
        try:
            user = self.github.get_user()
            lines: list[str] = []
            for i, repo in enumerate(user.get_repos()):
                if i >= limit:
                    lines.append("... (truncated)")
                    break
                suffix = " (private)" if repo.private else ""
                lines.append(f"- {repo.full_name}{suffix}")
            body = "\n".join(lines) or "(none)"
            return f"Repositories visible to @{user.login}:\n{body}"
        except Exception as exc:
            return self._describe_error(exc)

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #

    def get_tools(self) -> list[FunctionTool]:
        return [
            # camel base: reads + create-PR
            FunctionTool(self.github_create_pull_request),
            FunctionTool(self.github_get_issue_list),
            FunctionTool(self.github_get_issue_content),
            FunctionTool(self.github_get_pull_request_list),
            FunctionTool(self.github_get_pull_request_code),
            FunctionTool(self.github_get_pull_request_comments),
            FunctionTool(self.github_get_all_file_paths),
            FunctionTool(self.github_retrieve_file_content),
            # Issue management
            FunctionTool(self.github_create_issue),
            FunctionTool(self.github_update_issue),
            FunctionTool(self.github_close_issue),
            FunctionTool(self.github_reopen_issue),
            FunctionTool(self.github_add_issue_comment),
            FunctionTool(self.github_get_issue_comments),
            FunctionTool(self.github_search_issues),
            # Pull request management
            FunctionTool(self.github_create_pull_request_from_branch),
            FunctionTool(self.github_get_pull_request),
            FunctionTool(self.github_merge_pull_request),
            FunctionTool(self.github_close_pull_request),
            FunctionTool(self.github_add_pull_request_comment),
            # Repository / branch
            FunctionTool(self.github_create_branch),
            FunctionTool(self.github_list_branches),
            FunctionTool(self.github_list_repositories),
        ]

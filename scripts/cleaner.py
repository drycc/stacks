#!/usr/bin/env python3
"""
Git Repository Cleaner

This script provides various cleanup operations for git repositories and GitHub issues.

Usage:
    python cleaner.py tags -n 3 [--dry-run] [--confirm]
    python cleaner.py issues --max-issues 100 [--dry-run]
"""

import argparse
import subprocess
import sys
import os
import requests
from collections import defaultdict
from typing import List, Dict, Tuple


def run_command(command: List[str], dry_run: bool = False) -> str:
    """Execute a shell command or print it in dry-run mode."""
    cmd_str = ' '.join(command)

    if dry_run:
        print(f"[DRY RUN] Would execute: {cmd_str}")
        return ""

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {cmd_str}")
        print(f"Error: {e.stderr}")
        return ""


def get_all_tags() -> List[str]:
    """Get all git tags from the repository."""
    try:
        result = subprocess.run(['git', 'tag', '-l'], capture_output=True, text=True, check=True)
        return result.stdout.strip().split('\n') if result.stdout.strip() else []
    except subprocess.CalledProcessError as e:
        print(f"Error getting tags: {e.stderr}")
        return []


def parse_tag(tag: str) -> Tuple[str, str]:
    """Parse a tag into stack name and version."""
    if '@' not in tag:
        raise ValueError(f"Invalid tag format: {tag}. Expected format: stack-name@version")

    stack_name, version = tag.split('@', 1)
    if not stack_name or not version:
        raise ValueError(f"Invalid tag format: {tag}")

    return stack_name, version


def group_tags_by_stack(tags: List[str]) -> Dict[str, List[Tuple[str, str]]]:
    """Group tags by stack name and sort versions for each stack."""
    stacks = defaultdict(list)

    for tag in tags:
        try:
            stack_name, version = parse_tag(tag)
            stacks[stack_name].append((tag, version))
        except ValueError as e:
            print(f"Warning: {e}", file=sys.stderr)
            continue

    # Sort versions for each stack (newest first)
    for stack_name in stacks:
        stacks[stack_name].sort(key=lambda x: x[1], reverse=True)

    return stacks


def get_tags_to_delete(stacks: Dict[str, List[Tuple[str, str]]], keep_count: int) -> List[str]:
    """Determine which tags should be deleted based on keep_count."""
    tags_to_delete = []

    for stack_name, tags in stacks.items():
        if len(tags) > keep_count:
            tags_to_delete.extend([tag[0] for tag in tags[keep_count:]])

    return tags_to_delete


def delete_tag(tag: str, dry_run: bool = False) -> bool:
    """Delete a tag both locally and remotely."""
    print(f"Processing tag: {tag}")

    # Delete local tag
    local_result = run_command(['git', 'tag', '-d', tag], dry_run)
    print(f"Delete local tag: {local_result}")
    # Delete remote tag
    remote_result = run_command(['git', 'push', 'origin', f':refs/tags/{tag}'], dry_run)
    print(f"Delete remote tag: {remote_result}")
    return True


def clean_tags(args):
    """Clean up old git tags for stacks."""
    if args.keep_count < 1:
        print("Error: keep-count must be at least 1", file=sys.stderr)
        sys.exit(1)

    print(f"Git Tag Cleaner - Keeping {args.keep_count} latest versions per stack")

    # Get all tags
    all_tags = get_all_tags()
    if not all_tags:
        print("No tags found in repository")
        return

    print(f"Found {len(all_tags)} total tags")

    # Group tags by stack
    stacks = group_tags_by_stack(all_tags)
    print(f"Found {len(stacks)} stacks")

    # Show tag distribution
    for stack_name, tags in sorted(stacks.items()):
        print(f"  {stack_name}: {len(tags)} versions")

    # Get tags to delete
    tags_to_delete = get_tags_to_delete(stacks, args.keep_count)

    if not tags_to_delete:
        print("No tags to delete - all stacks have <= {} versions".format(args.keep_count))
        return

    print(f"\nFound {len(tags_to_delete)} tags to delete:")
    for tag in sorted(tags_to_delete):
        print(f"  - {tag}")

    # Confirm deletion
    if not args.dry_run and not args.confirm:
        response = input(f"\nDelete these {len(tags_to_delete)} tags? (y/N): ")
        if response.lower() != 'y':
            print("Aborted by user")
            return

    # Delete tags
    success_count = 0
    for tag in tags_to_delete:
        try:
            delete_tag(tag, args.dry_run)
            success_count += 1
        except Exception as e:
            print(f"Error deleting tag {tag}: {e}", file=sys.stderr)

    print(f"\nCompleted: {success_count}/{len(tags_to_delete)} tags processed")


def clean_github_issues(args):
    """Clean GitHub issues to keep only the most recent ones."""
    github_headers = {'Authorization': 'token %s' % os.environ.get("GITHUB_TOKEN")}

    if not os.environ.get("GITHUB_TOKEN"):
        print("Error: GITHUB_TOKEN environment variable is required")
        return

    max_issues = args.max_issues
    all_issues = _fetch_all_issues(github_headers)

    if len(all_issues) <= max_issues:
        print(f"No issues to clean. Found {len(all_issues)} total issues, keeping {max_issues}")
        return

    issues_to_process = all_issues[max_issues:]
    print(f"Found {len(all_issues)} total issues")
    print(f"Will keep {max_issues} most recent issues")
    print(f"Will close and delete {len(issues_to_process)} oldest issues")

    for issue in issues_to_process:
        _process_issue_with_graphql(issue, args.dry_run, github_headers)


def _fetch_all_issues(headers: Dict[str, str]) -> List[Dict]:
    """Fetch all GitHub issues with pagination."""
    all_issues = []
    page = 1
    per_page = 100

    while True:
        issues_url = "https://api.github.com/repos/drycc/stacks/issues"
        params = {
            'state': 'all',
            'sort': 'created',
            'direction': 'desc',
            'per_page': per_page,
            'page': page
        }

        try:
            response = requests.get(issues_url, headers=headers, params=params)
            response.raise_for_status()
            issues = response.json()

            if not issues:
                break

            all_issues.extend(issues)
            page += 1

            if page > 50:  # Max 5000 issues
                break

        except requests.exceptions.RequestException as e:
            print(f"Error fetching issues on page {page}: {e}")
            break

    return all_issues


def _process_issue_with_graphql(issue: Dict, dry_run: bool, headers: Dict[str, str]) -> None:
    """Process a single issue using GraphQL API to delete by node_id."""
    import time

    issue_number = issue['number']
    issue_title = issue['title']

    if dry_run:
        print(f"[DRY RUN] Would delete issue #{issue_number}: {issue_title}")
        return

    # First, get the node_id for the issue
    node_id = _get_issue_node_id(issue_number, headers)
    if not node_id:
        print(f"Could not get node_id for issue #{issue_number}, attempting to close instead")
        _close_issue(issue_number, issue_title, headers)
        return

    # Use GraphQL to delete the issue
    graphql_url = "https://api.github.com/graphql"
    graphql_query = {
        "query": f'mutation {{ deleteIssue(input: {{issueId: "{node_id}"}}) {{ clientMutationId }} }}'
    }

    try:
        response = requests.post(graphql_url, headers=headers, json=graphql_query)
        response.raise_for_status()
        
        result = response.json()
        if 'errors' in result:
            error_message = result['errors'][0].get('message', 'Unknown error')
            print(f"GraphQL error deleting issue #{issue_number}: {error_message}")
            print(f"Attempting to close issue #{issue_number} instead")
            _close_issue(issue_number, issue_title, headers)
        else:
            print(f"Deleted issue #{issue_number}: {issue_title}")
    except requests.exceptions.RequestException as e:
        print(f"Error deleting issue #{issue_number} via GraphQL: {e}")
        print(f"Attempting to close issue #{issue_number} instead")
        _close_issue(issue_number, issue_title, headers)

    time.sleep(0.2)  # Rate limiting


def _get_issue_node_id(issue_number: int, headers: Dict[str, str]) -> str:
    """Get the node_id for a specific issue number."""
    issue_url = f"https://api.github.com/repos/drycc/stacks/issues/{issue_number}"
    
    try:
        response = requests.get(issue_url, headers=headers)
        response.raise_for_status()
        issue_data = response.json()
        return issue_data.get('node_id')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching node_id for issue #{issue_number}: {e}")
        return None


def _close_issue(issue_number: int, issue_title: str, headers: Dict[str, str]) -> None:
    """Close an issue if deletion fails."""
    close_url = f"https://api.github.com/repos/drycc/stacks/issues/{issue_number}"
    close_data = {'state': 'closed'}

    try:
        close_response = requests.patch(close_url, headers=headers, json=close_data)
        close_response.raise_for_status()
        print(f"Closed issue #{issue_number}: {issue_title} (could not delete)")
    except requests.exceptions.RequestException as e:
        print(f"Error closing issue #{issue_number}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description='Git repository cleaner with various cleanup operations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cleaner.py tags -n 3              # Keep 3 latest versions per stack
  python cleaner.py tags -n 5 --dry-run    # Preview tag cleanup
  python cleaner.py tags -n 2 --confirm    # Skip confirmation prompt
  python cleaner.py issues --max-issues 50 # Keep 50 most recent issues
  python cleaner.py issues --dry-run       # Preview issue cleanup

Note: Issues cleanup requires admin permissions to delete issues.
If deletion fails, issues will be closed instead.
        """
    )

    subparsers = parser.add_subparsers(dest='action', help='Cleanup action to perform')

    # Tags cleanup parser
    tags_parser = subparsers.add_parser('tags', help='Clean up old git tags')
    tags_parser.add_argument('-n', '--keep-count', type=int, required=True,
                            help='Number of latest versions to keep for each stack')
    tags_parser.add_argument('--dry-run', action='store_true',
                            help='Only print commands without executing them')
    tags_parser.add_argument('--confirm', action='store_true',
                            help='Skip confirmation prompt and execute directly')

    # Issues cleanup parser
    issues_parser = subparsers.add_parser('issues', help='Clean up GitHub issues')
    issues_parser.add_argument('--max-issues', type=int, default=100,
                              help='Maximum number of issues to keep (default: 100)')
    issues_parser.add_argument('--dry-run', action='store_true',
                             help='Only print commands without executing them')

    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        sys.exit(1)

    if args.action == 'tags':
        clean_tags(args)
    elif args.action == 'issues':
        clean_github_issues(args)
    else:
        parser.error(f"Unknown action: {args.action}")


if __name__ == '__main__':
    main()

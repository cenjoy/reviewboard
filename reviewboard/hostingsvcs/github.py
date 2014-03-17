from __future__ import unicode_literals

import json
from collections import defaultdict
from django.conf.urls import patterns, url
from django.core.cache import cache
from django.http import HttpResponse
from django.utils import six
from django.utils.six.moves import http_client
from django.utils.six.moves.urllib.error import HTTPError, URLError
from django.views.decorators.http import require_POST
from reviewboard.hostingsvcs.hook_utils import (close_all_review_requests,
                                                get_git_branch_name,
                                                get_review_request_id,
                                                get_server_url)
from reviewboard.scmtools.core import Branch, Commit
from reviewboard.scmtools.errors import FileNotFoundError, SCMError
                                 '%(github_public_repo_name)s/'
                                 'issues#issue/%%s',
    supports_post_commit = True
    supports_repositories = True
    repository_url_patterns = patterns(
        '',

        url(r'^hooks/post-receive/$',
            'reviewboard.hostingsvcs.github._process_post_receive_hook'),
    )

        except Exception as e:
            if six.text_type(e) == 'Not Found':
                        _('A repository with this organization or name was '
                          'not found.'))
                body=json.dumps(body))
        except (HTTPError, URLError) as e:
                rsp = json.loads(data)
                raise AuthorizationError(six.text_type(e))
        except (URLError, HTTPError):
        except (URLError, HTTPError):
    def get_branches(self, repository):
        results = []

        url = self._build_api_url(self._get_repo_api_url(repository),
                                  'git/refs/heads')

        try:
            rsp = self._api_get(url)
        except Exception as e:
            logging.warning('Failed to fetch commits from %s: %s',
                            url, e)
            return results

        for ref in rsp:
            refname = ref['ref']

            if not refname.startswith('refs/heads/'):
                continue

            name = refname.split('/')[-1]
            results.append(Branch(name, ref['object']['sha'],
                                  default=(name == 'master')))

        return results

    def get_commits(self, repository, start=None):
        results = []

        resource = 'commits'
        url = self._build_api_url(self._get_repo_api_url(repository), resource)

        if start:
            url += '&sha=%s' % start

        try:
            rsp = self._api_get(url)
        except Exception as e:
            logging.warning('Failed to fetch commits from %s: %s',
                            url, e)
            return results

        for item in rsp:
            commit = Commit(
                item['commit']['author']['name'],
                item['sha'],
                item['commit']['committer']['date'],
                item['commit']['message'])
            if item['parents']:
                commit.parent = item['parents'][0]['sha']

            results.append(commit)

        return results

    def get_change(self, repository, revision):
        repo_api_url = self._get_repo_api_url(repository)

        # Step 1: fetch the commit itself that we want to review, to get
        # the parent SHA and the commit message. Hopefully this information
        # is still in cache so we don't have to fetch it again.
        commit = cache.get(repository.get_commit_cache_key(revision))
        if commit:
            author_name = commit.author_name
            date = commit.date
            parent_revision = commit.parent
            message = commit.message
        else:
            url = self._build_api_url(repo_api_url, 'commits')
            url += '&sha=%s' % revision

            try:
                commit = self._api_get(url)[0]
            except Exception as e:
                raise SCMError(six.text_type(e))

            author_name = commit['commit']['author']['name']
            date = commit['commit']['committer']['date'],
            parent_revision = commit['parents'][0]['sha']
            message = commit['commit']['message']

        # Step 2: fetch the "compare two commits" API to get the diff if the
        # commit has a parent commit. Otherwise, fetch the commit itself.
        if parent_revision:
            url = self._build_api_url(
                repo_api_url, 'compare/%s...%s' % (parent_revision, revision))
        else:
            url = self._build_api_url(repo_api_url, 'commits/%s' % revision)

        try:
            comparison = self._api_get(url)
        except Exception as e:
            raise SCMError(six.text_type(e))

        if parent_revision:
            tree_sha = comparison['base_commit']['commit']['tree']['sha']
        else:
            tree_sha = comparison['commit']['tree']['sha']

        files = comparison['files']

        # Step 3: fetch the tree for the original commit, so that we can get
        # full blob SHAs for each of the files in the diff.
        url = self._build_api_url(repo_api_url, 'git/trees/%s' % tree_sha)
        url += '&recursive=1'
        tree = self._api_get(url)

        file_shas = {}
        for file in tree['tree']:
            file_shas[file['path']] = file['sha']

        diff = []

        for file in files:
            filename = file['filename']
            status = file['status']
            try:
                patch = file['patch']
            except KeyError:
                continue

            diff.append('diff --git a/%s b/%s' % (filename, filename))

            if status == 'modified':
                old_sha = file_shas[filename]
                new_sha = file['sha']
                diff.append('index %s..%s 100644' % (old_sha, new_sha))
                diff.append('--- a/%s' % filename)
                diff.append('+++ b/%s' % filename)
            elif status == 'added':
                new_sha = file['sha']

                diff.append('new file mode 100644')
                diff.append('index %s..%s' % ('0' * 40, new_sha))
                diff.append('--- /dev/null')
                diff.append('+++ b/%s' % filename)
            elif status == 'removed':
                old_sha = file_shas[filename]

                diff.append('deleted file mode 100644')
                diff.append('index %s..%s' % (old_sha, '0' * 40))
                diff.append('--- a/%s' % filename)
                diff.append('+++ /dev/null')

            diff.append(patch)

        diff = '\n'.join(diff)

        # Make sure there's a trailing newline
        if not diff.endswith('\n'):
            diff += '\n'

        return Commit(author_name, revision, date, message, parent_revision,
                      diff=diff)

        elif ('errors' in rsp and
              status_code == http_client.UNPROCESSABLE_ENTITY):
                                  owner, repo_name)
            return json.loads(data)
        except (URLError, HTTPError) as e:
                rsp = json.loads(data)
                raise Exception(six.text_type(e))


@require_POST
def _process_post_receive_hook(request, *args, **kwargs):
    """Closes review requests as submitted automatically after a push."""
    try:
        payload = json.loads(request.body)
    except ValueError, e:
        logging.error('The payload is not in JSON format: %s', e)
        return HttpResponse(status=415)

    server_url = get_server_url(request)
    review_id_to_commits = _get_review_id_to_commits_map(payload, server_url)

    if not review_id_to_commits:
        return HttpResponse()

    close_all_review_requests(review_id_to_commits)

    return HttpResponse()


def _get_review_id_to_commits_map(payload, server_url):
    """Returns a dictionary, mapping a review request ID to a list of commits.

    If a commit's commit message does not contain a review request ID, we append
    the commit to the key 0.
    """
    review_id_to_commits_map = defaultdict(list)

    ref_name = payload.get('ref', None)
    branch_name = get_git_branch_name(ref_name)

    if not branch_name:
        return None

    commits = payload.get('commits', [])

    for commit in commits:
        commit_hash = commit.get('id', None)
        commit_message = commit.get('message', None)
        review_request_id = get_review_request_id(commit_message, server_url)

        commit_entry = '%s (%s)' % (branch_name, commit_hash[:7])
        review_id_to_commits_map[review_request_id].append(commit_entry)

    return review_id_to_commits_map
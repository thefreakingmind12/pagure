# -*- coding: utf-8 -*-

"""
 (c) 2015 - Copyright Red Hat Inc

 Authors:
   Pierre-Yves Chibon <pingou@pingoured.fr>

"""

__requires__ = ['SQLAlchemy >= 0.8']
import pkg_resources

import json
import unittest
import shutil
import sys
import tempfile
import os

import pygit2
from mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(
    os.path.abspath(__file__)), '..'))

import pagure.lib
import tests


class PagureFlaskForktests(tests.Modeltests):
    """ Tests for flask fork controller of pagure """

    def setUp(self):
        """ Set up the environnment, ran before every tests. """
        super(PagureFlaskForktests, self).setUp()

        pagure.APP.config['TESTING'] = True
        pagure.SESSION = self.session
        pagure.ui.SESSION = self.session
        pagure.ui.app.SESSION = self.session
        pagure.ui.fork.SESSION = self.session
        pagure.ui.repo.SESSION = self.session

        pagure.APP.config['GIT_FOLDER'] = os.path.join(tests.HERE, 'repos')
        pagure.APP.config['FORK_FOLDER'] = os.path.join(tests.HERE, 'forks')
        pagure.APP.config['TICKETS_FOLDER'] = os.path.join(
            tests.HERE, 'tickets')
        pagure.APP.config['DOCS_FOLDER'] = os.path.join(
            tests.HERE, 'docs')
        pagure.APP.config['REQUESTS_FOLDER'] = os.path.join(
            tests.HERE, 'requests')
        self.app = pagure.APP.test_client()

    def set_up_git_repo(self, new_project=None, branch_from='feature'):
        """ Set up the git repo and create the corresponding PullRequest
        object.
        """

        # Create a git repo to play with
        gitrepo = os.path.join(tests.HERE, 'repos', 'test.git')
        self.assertFalse(os.path.exists(gitrepo))
        os.makedirs(gitrepo)
        repo = pygit2.init_repository(gitrepo, bare=True)

        newpath = tempfile.mkdtemp(prefix='pagure-fork-test')
        clone_repo = pygit2.clone_repository(gitrepo, newpath)

        # Create a file in that git repo
        with open(os.path.join(newpath, 'sources'), 'w') as stream:
            stream.write('foo\n bar')
        clone_repo.index.add('sources')
        clone_repo.index.write()

        # Commits the files added
        tree = clone_repo.index.write_tree()
        author = pygit2.Signature(
            'Alice Author', 'alice@authors.tld')
        committer = pygit2.Signature(
            'Cecil Committer', 'cecil@committers.tld')
        clone_repo.create_commit(
            'refs/heads/master',  # the name of the reference to update
            author,
            committer,
            'Add sources file for testing',
            # binary string representing the tree object ID
            tree,
            # list of binary strings representing parents of the new commit
            []
        )
        refname = 'refs/heads/master:refs/heads/master'
        ori_remote = clone_repo.remotes[0]
        ori_remote.push(refname)

        first_commit = repo.revparse_single('HEAD')

        # Set the second repo

        new_gitrepo = newpath
        if new_project:
            # Create a new git repo to play with
            new_gitrepo = new_project.path
            if not os.path.exists(new_gitrepo):
                os.makedirs(new_gitrepo)
                new_repo = pygit2.clone_repository(gitrepo, new_gitrepo)

        repo = pygit2.Repository(new_gitrepo)

        # Edit the sources file again
        with open(os.path.join(new_gitrepo, 'sources'), 'w') as stream:
            stream.write('foo\n bar\nbaz\n boose')
        repo.index.add('sources')
        repo.index.write()

        # Commits the files added
        tree = repo.index.write_tree()
        author = pygit2.Signature(
            'Alice Author', 'alice@authors.tld')
        committer = pygit2.Signature(
            'Cecil Committer', 'cecil@committers.tld')
        repo.create_commit(
            'refs/heads/%s' % branch_from,
            author,
            committer,
            'A commit on branch %s' % branch_from,
            tree,
            [first_commit.oid.hex]
        )
        refname = 'refs/heads/%s:refs/heads/%s' % (branch_from, branch_from)
        ori_remote = clone_repo.remotes[0]
        ori_remote.push(refname)

        second_commit = repo.revparse_single('HEAD')

        # Create a PR for these changes
        project = pagure.lib.get_project(self.session, 'test')
        msg = pagure.lib.new_pull_request(
            session=self.session,
            repo_from=project,
            branch_from=branch_from,
            repo_to=project,
            branch_to='master',
            title='PR from the %s branch' % branch_from,
            user='pingou',
            requestfolder=None,
        )
        self.session.commit()
        self.assertEqual(msg, 'Request created')

    @patch('pagure.lib.notify.send_email')
    def test_request_pull(self, send_email):
        """ Test the request_pull endpoint. """
        send_email.return_value = True

        tests.create_projects(self.session)
        tests.create_projects_git(
            os.path.join(tests.HERE, 'requests'), bare=True)

        # Non-existant project
        output = self.app.get('/foobar/pull-request/1')
        self.assertEqual(output.status_code, 404)

        # Project has no PR
        output = self.app.get('/test/pull-request/1')
        self.assertEqual(output.status_code, 404)

        self.set_up_git_repo(new_project=None, branch_from='feature')

        project = pagure.lib.get_project(self.session, 'test')
        self.assertEqual(len(project.requests), 1)

        # View the pull-request
        output = self.app.get('/test/pull-request/1')
        self.assertEqual(output.status_code, 200)
        self.assertIn(
            '<title>Pull request #1 - test - Pagure</title>', output.data)
        self.assertIn(
            'title="View file as of 2a552b">View</a>', output.data)

    @patch('pagure.lib.notify.send_email')
    def test_merge_request_pull_FF(self, send_email):
        """ Test the merge_request_pull endpoint. """
        send_email.return_value = True

        self.test_request_pull()

        user = tests.FakeUser()
        with tests.user_set(pagure.APP, user):
            output = self.app.get('/test/pull-request/1')
            self.assertEqual(output.status_code, 200)

            csrf_token = output.data.split(
                'name="csrf_token" type="hidden" value="')[1].split('">')[0]

            # No CSRF
            output = self.app.post(
                '/test/pull-request/1/merge', data={}, follow_redirects=True)
            self.assertEqual(output.status_code, 200)
            self.assertIn(
                '<title>Pull request #1 - test - Pagure</title>', output.data)
            self.assertIn(
                'title="View file as of 2a552b">View</a>', output.data)

            # Wrong project
            data = {
                'csrf_token': csrf_token,
            }
            output = self.app.post(
                '/foobar/pull-request/100/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 404)

            # Wrong project
            data = {
                'csrf_token': csrf_token,
            }
            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 403)

        user.username = 'pingou'
        with tests.user_set(pagure.APP, user):

            # Wrong request id
            data = {
                'csrf_token': csrf_token,
            }
            output = self.app.post(
                '/test/pull-request/100/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 404)

            # Project w/o pull-request
            repo = pagure.lib.get_project(self.session, 'test')
            settings = repo.settings
            settings['pull_requests'] = False
            repo.settings = settings
            self.session.add(repo)
            self.session.commit()

            # Pull-request disabled
            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 404)

            # Project w pull-request but only assignee can merge
            settings['pull_requests'] = True
            settings['Only_assignee_can_merge_pull-request'] = True
            repo.settings = settings
            self.session.add(repo)
            self.session.commit()

            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 200)
            self.assertIn(
                '<title>Pull request #1 - test - Pagure</title>',
                output.data)
            self.assertIn(
                '<li class="error">This request must be assigned to be merged</li>',
                output.data)

            # PR assigned but not to this user
            repo = pagure.lib.get_project(self.session, 'test')
            req = repo.requests[0]
            req.assignee_id = 2
            self.session.add(req)
            self.session.commit()

            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 200)
            self.assertIn(
                '<title>Pull request #1 - test - Pagure</title>',
                output.data)
            self.assertIn(
                '<li class="error">Only the assignee can merge this review</li>',
                output.data)

            # Project w/ minimal PR score
            settings['Only_assignee_can_merge_pull-request'] = False
            settings['Minimum_score_to_merge_pull-request'] = 2
            repo.settings = settings
            self.session.add(repo)
            self.session.commit()

            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 200)
            self.assertIn(
                '<title>Pull request #1 - test - Pagure</title>',
                output.data)
            self.assertIn(
                '<li class="error">This request does not have the minimum '
                'review score necessary to be merged</li>', output.data)

            # Merge
            settings['Minimum_score_to_merge_pull-request'] = -1
            repo.settings = settings
            self.session.add(repo)
            self.session.commit()
            output = self.app.post(
                '/test/pull-request/1/merge', data=data, follow_redirects=True)
            self.assertEqual(output.status_code, 200)
            self.assertIn(
                '<title>Overview - test - Pagure</title>', output.data)
            self.assertIn(
                '<li class="message">Changes merged!</li>', output.data)


if __name__ == '__main__':
    SUITE = unittest.TestLoader().loadTestsFromTestCase(PagureFlaskForktests)
    unittest.TextTestRunner(verbosity=2).run(SUITE)

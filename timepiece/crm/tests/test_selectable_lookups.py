"""Directory lookups mounted under the selectable URL prefix.

These tests describe the access rules for the registered lookups. They fail
while an anonymous or under-authorized request can still read rows.
"""
import json

from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase

from timepiece.crm.lookups import (BusinessLookup, ProjectLookup, QuickLookup,
        UserLookup)
from timepiece.tests import factories
from timepiece.tests.base import ViewTestMixin


def _permission(perm_label):
    app_label, codename = perm_label.split('.')
    if app_label == 'auth' and codename == 'view_user':
        content_type = ContentType.objects.get(app_label='auth', model='user')
        permission, _created = Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={'name': 'Can view user'},
        )
        return permission
    return Permission.objects.get(
        content_type__app_label=app_label,
        codename=codename,
    )


class SelectableLookupTests(ViewTestMixin, TestCase):
    """Shared setup for selectable directory lookups."""

    def setUp(self):
        super(SelectableLookupTests, self).setUp()
        self.listed_user = factories.User(
            username='hiddenperson',
            first_name='Hidden',
            last_name='DirectoryPerson',
            email='hidden.person@directory.example',
        )
        self.page_one_user = factories.User(
            username='walkaaa',
            first_name='WalkPage',
            last_name='AaaWalk',
            email='walk.aaa@directory.example',
        )
        self.page_two_user = factories.User(
            username='walkzzz',
            first_name='WalkPage',
            last_name='ZzzWalk',
            email='walk.zzz@directory.example',
        )
        self.client_business = factories.Business(
            name='ClientTokenBiz',
            short_name='ClientTok',
        )
        self.listed_project = factories.Project(
            name='ApolloDirectoryProject',
            business=self.client_business,
        )
        self.quick_user = factories.User(
            username='quickperson',
            first_name='QuickTokenUser',
            last_name='Example',
            email='quick.person@directory.example',
        )
        self.quick_business = factories.Business(name='QuickTokenBusiness')
        self.quick_project = factories.Project(
            name='QuickTokenProject',
            business=self.quick_business,
        )

    def lookup_url(self, lookup):
        url = lookup.url()
        self.assertTrue(url.startswith('/selectable/'))
        self.assertEqual(url, '/selectable/{0}/'.format(lookup.name()))
        return url

    def anonymous_get(self, lookup, params):
        client = Client()
        self.assertEqual(len(client.cookies), 0)
        return client.get(self.lookup_url(lookup), params)

    def authorized_get(self, user, lookup, params):
        self.login_user(user)
        return self.client.get(self.lookup_url(lookup), params)

    def grant(self, user, *perm_labels):
        for perm_label in perm_labels:
            user.user_permissions.add(_permission(perm_label))
        if hasattr(user, '_perm_cache'):
            del user._perm_cache
        return user

    def assert_hidden(self, response, secrets):
        body = response.content
        leaked = [secret for secret in secrets if secret in body]
        self.assertEqual(leaked, [],
            'Lookup disclosed {0} with status {1}: {2}'.format(
                leaked, response.status_code, body[:500]))
        self.assertIn(response.status_code, (401, 403, 302),
            'Lookup returned status {0} instead of refusing.'.format(
                response.status_code))

    def assert_listed(self, response, expected_ids, expected_values):
        self.assertEqual(response.status_code, 200, response.content[:500])
        payload = json.loads(response.content)
        rows = payload['data']
        ids = [row['id'] for row in rows]
        values = [row['value'] for row in rows]
        for expected_id in expected_ids:
            self.assertIn(expected_id, ids)
        for expected_value in expected_values:
            self.assertIn(expected_value, values)


class AnonymousSelectableLookupTests(SelectableLookupTests):
    """No session cookie. Every registered lookup must refuse."""

    def test_user_lookup_short_term_is_hidden(self):
        response = self.anonymous_get(UserLookup, {'term': 'Hidden'})
        self.assert_hidden(response, [
            'Hidden DirectoryPerson',
            'hiddenperson',
            'hidden.person@directory.example',
        ])

    def test_user_lookup_email_term_does_not_confirm_account(self):
        response = self.anonymous_get(UserLookup, {
            'term': 'hidden.person@directory.example',
        })
        # The query itself may be echoed. The account name must not be.
        self.assert_hidden(response, [
            'Hidden DirectoryPerson',
            'hiddenperson',
        ])

    def test_user_lookup_second_page_is_hidden(self):
        response = self.anonymous_get(UserLookup, {
            'term': 'WalkPage',
            'limit': 1,
            'page': 2,
        })
        self.assert_hidden(response, [
            'WalkPage AaaWalk',
            'WalkPage ZzzWalk',
            'walkaaa',
            'walkzzz',
        ])

    def test_user_lookup_empty_term_is_hidden(self):
        response = self.anonymous_get(UserLookup, {'term': ''})
        self.assert_hidden(response, [
            'Hidden DirectoryPerson',
            'WalkPage ZzzWalk',
        ])

    def test_project_lookup_by_project_name_is_hidden(self):
        response = self.anonymous_get(ProjectLookup, {
            'term': 'ApolloDirectoryProject',
        })
        self.assert_hidden(response, ['ApolloDirectoryProject'])

    def test_project_lookup_by_client_name_is_hidden(self):
        response = self.anonymous_get(ProjectLookup, {
            'term': 'ClientTokenBiz',
        })
        self.assert_hidden(response, [
            'ApolloDirectoryProject',
            'ClientTokenBiz',
        ])

    def test_business_lookup_by_name_is_hidden(self):
        response = self.anonymous_get(BusinessLookup, {
            'term': 'ClientTokenBiz',
        })
        self.assert_hidden(response, ['ClientTokenBiz'])

    def test_business_lookup_by_short_name_is_hidden(self):
        response = self.anonymous_get(BusinessLookup, {'term': 'ClientTok'})
        self.assert_hidden(response, ['ClientTokenBiz', 'ClientTok'])

    def test_quick_lookup_is_hidden(self):
        response = self.anonymous_get(QuickLookup, {'term': 'QuickToken'})
        self.assert_hidden(response, [
            'QuickTokenUser Example',
            'QuickTokenProject',
            'QuickTokenBusiness',
            'quickperson',
        ])


class UnauthorizedSelectableLookupTests(SelectableLookupTests):
    """A signed-in user still needs the permission of a page that embeds the lookup."""

    def setUp(self):
        super(UnauthorizedSelectableLookupTests, self).setUp()
        self.user = factories.User()
        self.login_user(self.user)

    def test_user_lookup_requires_project_permission(self):
        response = self.client.get(self.lookup_url(UserLookup), {
            'term': 'hidden.person@directory.example',
        })
        self.assert_hidden(response, ['Hidden DirectoryPerson', 'hiddenperson'])

    def test_project_lookup_requires_project_page_permission(self):
        response = self.client.get(self.lookup_url(ProjectLookup), {
            'term': 'ApolloDirectoryProject',
        })
        self.assert_hidden(response, ['ApolloDirectoryProject'])

    def test_business_lookup_requires_project_edit_permission(self):
        response = self.client.get(self.lookup_url(BusinessLookup), {
            'term': 'ClientTokenBiz',
        })
        self.assert_hidden(response, ['ClientTokenBiz'])

    def test_quick_lookup_allows_any_signed_in_user(self):
        response = self.client.get(self.lookup_url(QuickLookup), {
            'term': 'QuickToken',
        })
        self.assert_listed(
            response,
            [
                'user-{0}'.format(self.quick_user.pk),
                'project-{0}'.format(self.quick_project.pk),
                'business-{0}'.format(self.quick_business.pk),
            ],
            [
                'QuickTokenUser Example',
                'QuickTokenProject',
                'QuickTokenBusiness',
            ],
        )


class AuthorizedSelectableLookupTests(SelectableLookupTests):
    """Each embedding page's permission is sufficient for that lookup."""

    def test_project_viewer_can_search_users(self):
        user = self.grant(factories.User(), 'crm.view_project')
        response = self.authorized_get(user, UserLookup, {
            'term': 'hidden.person@directory.example',
        })
        self.assert_listed(
            response,
            [self.listed_user.pk],
            [self.listed_user.get_name_or_username()],
        )

    def test_relationship_creator_can_search_users(self):
        user = self.grant(factories.User(), 'crm.add_projectrelationship')
        response = self.authorized_get(user, UserLookup, {'term': 'Hidden'})
        self.assert_listed(
            response,
            [self.listed_user.pk],
            ['Hidden DirectoryPerson'],
        )

    def test_user_viewer_can_search_projects(self):
        user = self.grant(factories.User(), 'auth.view_user')
        response = self.authorized_get(user, ProjectLookup, {
            'term': 'ApolloDirectoryProject',
        })
        self.assert_listed(
            response,
            [self.listed_project.pk],
            ['ApolloDirectoryProject'],
        )

    def test_relationship_creator_can_search_projects(self):
        user = self.grant(factories.User(), 'crm.add_projectrelationship')
        response = self.authorized_get(user, ProjectLookup, {
            'term': 'ClientTokenBiz',
        })
        self.assert_listed(
            response,
            [self.listed_project.pk],
            ['ApolloDirectoryProject'],
        )

    def test_report_viewer_can_search_projects(self):
        user = self.grant(factories.User(), 'entries.view_entry_summary')
        response = self.authorized_get(user, ProjectLookup, {
            'term': 'ApolloDirectoryProject',
        })
        self.assert_listed(
            response,
            [self.listed_project.pk],
            ['ApolloDirectoryProject'],
        )

    def test_project_creator_can_search_businesses(self):
        user = self.grant(factories.User(), 'crm.add_project')
        response = self.authorized_get(user, BusinessLookup, {
            'term': 'ClientTok',
        })
        self.assert_listed(
            response,
            [self.client_business.pk],
            ['ClientTokenBiz'],
        )

    def test_project_editor_can_search_businesses(self):
        user = self.grant(factories.User(), 'crm.change_project')
        response = self.authorized_get(user, BusinessLookup, {
            'term': 'ClientTokenBiz',
        })
        self.assert_listed(
            response,
            [self.client_business.pk],
            ['ClientTokenBiz'],
        )

    def test_project_viewer_can_page_through_users(self):
        user = self.grant(factories.User(), 'crm.view_project')
        response = self.authorized_get(user, UserLookup, {
            'term': 'WalkPage',
            'limit': 1,
            'page': 2,
        })
        self.assert_listed(
            response,
            [self.page_two_user.pk],
            ['WalkPage ZzzWalk'],
        )
        payload = json.loads(response.content)
        self.assertEqual(len(payload['data']), 1)
        self.assertNotIn(self.page_one_user.pk,
            [row['id'] for row in payload['data']])

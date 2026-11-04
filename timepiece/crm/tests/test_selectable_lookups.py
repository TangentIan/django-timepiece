"""Directory lookups must follow the same rules as the list pages.

Anonymous clients, and signed-in users who lack the matching list
permission, must not be able to page through or search the user, project,
business, or quick lookups. The user lookup must not match on email.
"""
import json

from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from timepiece.crm.lookups import (BusinessLookup, ProjectLookup, QuickLookup,
        UserLookup)
from timepiece.crm.models import Attribute, Business, Project
from timepiece.tests.base import ViewTestMixin


def make_user(username, first_name, last_name, email, is_staff=False):
    user = User(
        username=username,
        first_name=first_name,
        last_name=last_name,
        email=email,
        is_staff=is_staff,
    )
    user.set_unusable_password()
    user.save()
    return user


def grant(user, app_label, model, codename):
    content_type = ContentType.objects.get(app_label=app_label, model=model)
    permission, created = Permission.objects.get_or_create(
        content_type=content_type,
        codename=codename,
        defaults={'name': 'Can %s' % codename},
    )
    user.user_permissions.add(permission)
    return permission


def display_name(user):
    return user.get_name_or_username()


class LookupAssertions(object):
    def assert_no_session_cookie(self):
        cookie = self.client.cookies.get(settings.SESSION_COOKIE_NAME)
        self.assertFalse(cookie)

    def assert_lookup_denied(self, response, leaked_snippets):
        self.assertNotEqual(
            response.status_code,
            200,
            'Lookup returned records to a caller who should be refused: %s'
            % response.content[:800],
        )
        body = response.content
        for snippet in leaked_snippets:
            if isinstance(snippet, unicode):
                snippet = snippet.encode('utf-8')
            elif not isinstance(snippet, str):
                snippet = str(snippet)
            self.assertNotIn(snippet, body)

    def result_payload(self, response):
        self.assertEqual(
            response.status_code,
            200,
            response.content[:800],
        )
        self.assertIn('application/json', response['Content-Type'])
        return json.loads(response.content)

    def result_ids(self, response):
        payload = self.result_payload(response)
        return [item['id'] for item in payload['data']]


class AnonymousSelectableDirectoryTests(LookupAssertions, ViewTestMixin,
        TestCase):
    def test_user_lookup_url_is_under_selectable_prefix(self):
        self.assertTrue(UserLookup.url().startswith('/selectable/'))
        self.assertTrue(ProjectLookup.url().startswith('/selectable/'))
        self.assertTrue(BusinessLookup.url().startswith('/selectable/'))
        self.assertTrue(QuickLookup.url().startswith('/selectable/'))

    def test_anonymous_cannot_page_the_user_directory(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        people = []
        for index in range(page_size + 1):
            people.append(make_user(
                'pageuser%02d' % index,
                'Listed',
                'Pageuser%02d' % index,
                'pageuser%02d@example.test' % index,
            ))
        first_page_name = display_name(people[0])

        self.assert_no_session_cookie()
        first_page = self.client.get(UserLookup.url(), {'term': ''})
        self.assert_lookup_denied(first_page, [first_page_name])

    def test_anonymous_cannot_request_the_second_user_page(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        people = []
        for index in range(page_size + 1):
            people.append(make_user(
                'pageuser%02d' % index,
                'Listed',
                'Pageuser%02d' % index,
                'pageuser%02d@example.test' % index,
            ))
        self.assert_no_session_cookie()
        second_page = self.client.get(UserLookup.url(), {
            'term': '',
            'page': 2,
            'limit': page_size,
        })
        self.assert_lookup_denied(second_page, [display_name(people[-1])])

    def test_anonymous_email_search_does_not_reveal_the_account(self):
        person = make_user(
            'directoryperson',
            'Visible',
            'Directoryperson',
            'hidden-address@example.test',
        )
        self.assert_no_session_cookie()
        response = self.client.get(UserLookup.url(), {'term': person.email})
        self.assert_lookup_denied(response, [display_name(person)])

    def test_anonymous_cannot_page_the_project_directory(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        business = Business.objects.create(name='Sharedclient')
        point_person = make_user(
            'pointperson', 'Point', 'Person', 'point@example.test',
            is_staff=True,
        )
        project_type = Attribute.objects.create(
            type=Attribute.PROJECT_TYPE, label='Consulting',
        )
        project_status = Attribute.objects.create(
            type=Attribute.PROJECT_STATUS, label='Active',
        )
        projects = []
        for index in range(page_size + 1):
            projects.append(Project.objects.create(
                name='Projpage%02d' % index,
                business=business,
                point_person=point_person,
                type=project_type,
                status=project_status,
                description='Listed work',
            ))

        self.assert_no_session_cookie()
        first_page = self.client.get(ProjectLookup.url(), {'term': ''})
        self.assert_lookup_denied(first_page, [projects[0].name])

    def test_anonymous_cannot_request_the_second_project_page(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        business = Business.objects.create(name='Sharedclient')
        point_person = make_user(
            'pointperson', 'Point', 'Person', 'point@example.test',
            is_staff=True,
        )
        project_type = Attribute.objects.create(
            type=Attribute.PROJECT_TYPE, label='Consulting',
        )
        project_status = Attribute.objects.create(
            type=Attribute.PROJECT_STATUS, label='Active',
        )
        last_name = 'Projpage%02d' % page_size
        for index in range(page_size + 1):
            Project.objects.create(
                name='Projpage%02d' % index,
                business=business,
                point_person=point_person,
                type=project_type,
                status=project_status,
                description='Listed work',
            )
        second_page = self.client.get(ProjectLookup.url(), {
            'term': '',
            'page': 2,
            'limit': page_size,
        })
        self.assert_lookup_denied(second_page, [last_name])

    def test_anonymous_cannot_page_the_business_directory(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        businesses = []
        for index in range(page_size + 1):
            businesses.append(Business.objects.create(
                name='Bizpage%02d' % index,
            ))

        self.assert_no_session_cookie()
        first_page = self.client.get(BusinessLookup.url(), {'term': ''})
        self.assert_lookup_denied(first_page, [businesses[0].name])

    def test_anonymous_cannot_request_the_second_business_page(self):
        page_size = settings.SELECTABLE_MAX_LIMIT
        last_name = 'Bizpage%02d' % page_size
        for index in range(page_size + 1):
            Business.objects.create(name='Bizpage%02d' % index)
        second_page = self.client.get(BusinessLookup.url(), {
            'term': '',
            'page': 2,
            'limit': page_size,
        })
        self.assert_lookup_denied(second_page, [last_name])

    def test_anonymous_quick_lookup_does_not_list_records_or_confirm_email(self):
        person = make_user(
            'quickperson',
            'Quick',
            'Person',
            'quick-hidden@example.test',
        )
        business = Business.objects.create(name='Quickclient')
        point_person = make_user(
            'quickpoint', 'Quick', 'Point', 'quick-point@example.test',
            is_staff=True,
        )
        project = Project.objects.create(
            name='Quickproject',
            business=business,
            point_person=point_person,
            type=Attribute.objects.create(
                type=Attribute.PROJECT_TYPE, label='Quick type',
            ),
            status=Attribute.objects.create(
                type=Attribute.PROJECT_STATUS, label='Quick status',
            ),
            description='Listed work',
        )
        leaked = [
            display_name(person),
            business.name,
            project.name,
        ]

        self.assert_no_session_cookie()
        empty = self.client.get(QuickLookup.url(), {'term': ''})
        self.assert_lookup_denied(empty, leaked)

        by_email = self.client.get(QuickLookup.url(), {'term': person.email})
        self.assert_lookup_denied(by_email, [display_name(person)])


class PermissionedSelectableDirectoryTests(LookupAssertions, ViewTestMixin,
        TestCase):
    def setUp(self):
        super(PermissionedSelectableDirectoryTests, self).setUp()
        self.reader = make_user(
            'lookupreader', 'Lookup', 'Reader', 'reader@example.test',
        )
        self.person = make_user(
            'directoryperson',
            'Visible',
            'Directoryperson',
            'hidden-address@example.test',
        )
        self.business = Business.objects.create(name='Secretclientco')
        self.project = Project.objects.create(
            name='Secretprojectalpha',
            business=self.business,
            point_person=self.reader,
            type=Attribute.objects.create(
                type=Attribute.PROJECT_TYPE, label='Consulting',
            ),
            status=Attribute.objects.create(
                type=Attribute.PROJECT_STATUS, label='Active',
            ),
            description='Listed work',
        )

    def login_with(self, *perms):
        for app_label, model, codename in perms:
            grant(self.reader, app_label, model, codename)
        self.login_user(self.reader)

    def test_signed_in_user_without_permissions_cannot_search(self):
        self.login_with()
        leaked_user = display_name(self.person)
        for url, snippets in (
            (UserLookup.url(), [leaked_user]),
            (ProjectLookup.url(), [self.project.name]),
            (BusinessLookup.url(), [self.business.name]),
            (QuickLookup.url(),
                [leaked_user, self.project.name, self.business.name]),
        ):
            response = self.client.get(url, {'term': ''})
            self.assert_lookup_denied(response, snippets)

    def test_view_user_permission_does_not_open_project_or_business_lookups(self):
        self.login_with(('auth', 'user', 'view_user'))

        users = self.client.get(UserLookup.url(), {'term': self.person.username})
        self.assertIn(self.person.pk, self.result_ids(users))

        projects = self.client.get(ProjectLookup.url(), {'term': ''})
        self.assert_lookup_denied(projects, [self.project.name])
        businesses = self.client.get(BusinessLookup.url(), {'term': ''})
        self.assert_lookup_denied(businesses, [self.business.name])

        quick = self.client.get(QuickLookup.url(), {'term': ''})
        if quick.status_code == 200:
            ids = self.result_ids(quick)
            self.assertNotIn('project-%s' % self.project.pk, ids)
            self.assertNotIn('business-%s' % self.business.pk, ids)
            self.assertNotIn(self.project.name, quick.content)
            self.assertNotIn(self.business.name, quick.content)
        else:
            self.assert_lookup_denied(
                quick, [self.project.name, self.business.name],
            )

    def test_view_project_permission_does_not_open_the_user_lookup(self):
        self.login_with(('crm', 'project', 'view_project'))
        projects = self.client.get(ProjectLookup.url(), {
            'term': self.project.name,
        })
        self.assertIn(self.project.pk, self.result_ids(projects))

        users = self.client.get(UserLookup.url(), {'term': ''})
        self.assert_lookup_denied(users, [display_name(self.person)])

    def test_view_business_permission_does_not_open_the_user_lookup(self):
        self.login_with(('crm', 'business', 'view_business'))
        businesses = self.client.get(BusinessLookup.url(), {
            'term': self.business.name,
        })
        self.assertIn(self.business.pk, self.result_ids(businesses))

        users = self.client.get(UserLookup.url(), {'term': ''})
        self.assert_lookup_denied(users, [display_name(self.person)])

    def test_user_lookup_matches_name_but_not_email(self):
        self.login_with(('auth', 'user', 'view_user'))

        by_username = self.client.get(UserLookup.url(), {
            'term': self.person.username,
        })
        payload = self.result_payload(by_username)
        ids = [item['id'] for item in payload['data']]
        self.assertIn(self.person.pk, ids)
        for item in payload['data']:
            self.assertNotIn(self.person.email, item['value'])
            self.assertNotIn(self.person.email, item['label'])
            self.assertNotIn('email', item)

        by_email = self.client.get(UserLookup.url(), {'term': self.person.email})
        if by_email.status_code != 200:
            self.assert_lookup_denied(by_email, [display_name(self.person)])
            return
        self.assertNotIn(self.person.pk, self.result_ids(by_email))
        for item in self.result_payload(by_email)['data']:
            self.assertNotEqual(item['id'], self.person.pk)

    def test_quick_lookup_email_does_not_confirm_an_account(self):
        self.login_with(
            ('auth', 'user', 'view_user'),
            ('crm', 'project', 'view_project'),
            ('crm', 'business', 'view_business'),
        )
        by_name = self.client.get(QuickLookup.url(), {
            'term': self.person.username,
        })
        self.assertIn(
            'user-%s' % self.person.pk,
            self.result_ids(by_name),
        )

        by_email = self.client.get(QuickLookup.url(), {
            'term': self.person.email,
        })
        if by_email.status_code != 200:
            self.assert_lookup_denied(by_email, [display_name(self.person)])
            return
        self.assertNotIn(
            'user-%s' % self.person.pk,
            self.result_ids(by_email),
        )

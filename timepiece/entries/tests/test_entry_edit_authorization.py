"""Authorization for editing time entries.

An employee who can edit entries must be able to change only their own
unverified entries. Someone with the payroll-summary permission may still
edit another person's entry. These tests are expected to fail until that
rule is enforced: a coworker can currently save a new project, activity,
location, comment, pause, and hours onto someone else's unverified row.
"""
from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client
from django.utils import timezone

from timepiece.entries.models import Entry
from timepiece.tests import factories
from timepiece.tests.base import ViewTestMixin


SNAPSHOT_FIELDS = (
    'user_id', 'project_id', 'activity_id', 'location_id', 'entry_group_id',
    'status', 'start_time', 'end_time', 'seconds_paused', 'pause_time',
    'comments', 'hours', 'date_updated',
)


def _entry_permissions(*codenames):
    return Permission.objects.filter(
        content_type=ContentType.objects.get_for_model(Entry),
        codename__in=codenames,
    )


class OtherUserEntryEditTests(ViewTestMixin, TestCase):
    """Coworkers with the ordinary change-entry permission."""

    def setUp(self):
        super(OtherUserEntryEditTests, self).setUp()
        # Enforce the CSRF check the edit form actually posts through.
        self.client = Client(enforce_csrf_checks=True)

        self.attacker = factories.User()
        self.victim = factories.User()
        self.payroll = factories.User()
        employee_perms = _entry_permissions(
            'can_clock_in', 'can_clock_out', 'can_pause', 'change_entry')
        self.attacker.user_permissions = employee_perms
        self.victim.user_permissions = employee_perms
        self.attacker.save()
        self.victim.save()
        payroll_perms = _entry_permissions(
            'change_entry', 'view_payroll_summary')
        self.payroll.user_permissions = payroll_perms
        self.payroll.save()

        self.activity = factories.Activity(code='WRK', name='Work')
        self.other_activity = factories.Activity(
            code='devl', name='development', billable=True)
        self.activity_group = factories.ActivityGroup(name='Client work')
        self.activity.activity_group.add(self.activity_group)
        self.other_activity.activity_group.add(self.activity_group)

        status = factories.StatusAttribute(
            label='Current', enable_timetracking=True)
        type_ = factories.TypeAttribute(
            label='Web Sites', enable_timetracking=True)
        self.business = factories.Business()
        self.project = factories.Project(
            type=type_, status=status, business=self.business,
            point_person=self.victim, activity_group=self.activity_group,
            name='Original project')
        self.other_project = factories.Project(
            type=type_, status=status, business=self.business,
            point_person=self.victim, activity_group=self.activity_group,
            name='Other project')
        factories.ProjectRelationship(user=self.victim, project=self.project)
        factories.ProjectRelationship(
            user=self.victim, project=self.other_project)
        factories.ProjectRelationship(user=self.attacker, project=self.project)
        factories.ProjectRelationship(
            user=self.attacker, project=self.other_project)
        self.location = factories.Location(name='Office', slug='office')
        self.other_location = factories.Location(name='Remote', slug='remote')

        self.now = timezone.now().replace(microsecond=0)
        self.victim_entry = factories.Entry(**{
            'user': self.victim,
            'project': self.project,
            'activity': self.activity,
            'location': self.location,
            'start_time': self.now - relativedelta(days=1, hours=4),
            'end_time': self.now - relativedelta(days=1, hours=3),
            'seconds_paused': 0,
            'comments': 'victim original comment',
            'status': Entry.UNVERIFIED,
        })
        self.victim_active = factories.Entry(**{
            'user': self.victim,
            'project': self.project,
            'activity': self.activity,
            'location': self.location,
            'start_time': self.now - relativedelta(minutes=30),
            'end_time': None,
            'seconds_paused': 0,
            'comments': 'victim active comment',
            'status': Entry.UNVERIFIED,
        })
        self.attacker_entry = factories.Entry(**{
            'user': self.attacker,
            'project': self.project,
            'activity': self.activity,
            'location': self.location,
            'start_time': self.now - relativedelta(days=8, hours=4),
            'end_time': self.now - relativedelta(days=8, hours=3),
            'seconds_paused': 0,
            'comments': 'attacker own comment',
            'status': Entry.UNVERIFIED,
        })
        self.verified_entry = factories.Entry(**{
            'user': self.victim,
            'project': self.project,
            'activity': self.activity,
            'location': self.location,
            'start_time': self.now - relativedelta(days=3, hours=4),
            'end_time': self.now - relativedelta(days=3, hours=3),
            'seconds_paused': 0,
            'comments': 'already verified',
            'status': Entry.VERIFIED,
        })
        self.login_user(self.attacker)

    def snapshot(self, entry):
        stored = Entry.no_join.get(pk=entry.pk)
        return dict((name, getattr(stored, name)) for name in SNAPSHOT_FIELDS)

    def csrf_token(self):
        """Token from a page the attacker is allowed to open."""
        response = self.client.get(reverse('create_entry'))
        self.assertEqual(response.status_code, 200)
        return self.client.cookies[settings.CSRF_COOKIE_NAME].value

    def rewritten_closed_data(self):
        start = self.now - relativedelta(days=1, hours=8)
        end = self.now - relativedelta(days=1, hours=6)
        return {
            'csrfmiddlewaretoken': self.csrf_token(),
            'project': self.other_project.pk,
            'location': self.other_location.pk,
            'activity': self.other_activity.pk,
            'seconds_paused': 120,
            'comments': 'rewritten by coworker',
            'start_time_0': start.strftime('%m/%d/%Y'),
            'start_time_1': start.strftime('%H:%M:%S'),
            'end_time_0': end.strftime('%m/%d/%Y'),
            'end_time_1': end.strftime('%H:%M:%S'),
        }

    def rewritten_active_data(self):
        start = self.now - relativedelta(days=2, hours=5)
        return {
            'csrfmiddlewaretoken': self.csrf_token(),
            'project': self.other_project.pk,
            'location': self.other_location.pk,
            'activity': self.other_activity.pk,
            'seconds_paused': 90,
            'comments': 'active entry rewritten by coworker',
            'start_time_0': start.strftime('%m/%d/%Y'),
            'start_time_1': start.strftime('%H:%M:%S'),
        }

    def assert_unchanged(self, entry, before, response):
        after = self.snapshot(entry)
        detail = 'status %s before %s after %s' % (
            response.status_code, before, after)
        if response.context and 'form' in response.context:
            detail += ' form errors %s' % response.context['form'].errors
        self.assertEqual(response.status_code, 404, detail)
        self.assertEqual(before, after, detail)
        self.assertNotIn('rewritten by coworker', response.content)
        self.assertNotIn('active entry rewritten', response.content)

    def test_entry_ids_are_consecutive_integers(self):
        """Ids assigned to successive entries can be guessed from one id."""
        self.assertEqual(self.victim_active.pk, self.victim_entry.pk + 1)
        self.assertEqual(self.attacker_entry.pk, self.victim_active.pk + 1)

    def test_coworker_get_of_unverified_entry_is_not_found(self):
        before = self.snapshot(self.victim_entry)
        url = reverse('edit_entry', args=(self.victim_entry.pk,))
        response = self.client.get(url)
        self.assert_unchanged(self.victim_entry, before, response)
        self.assertNotIn('victim original comment', response.content)

    def test_coworker_cannot_rewrite_unverified_closed_entry(self):
        before = self.snapshot(self.victim_entry)
        attacker_before = self.snapshot(self.attacker_entry)
        count = Entry.no_join.count()
        url = reverse('edit_entry', args=(self.victim_entry.pk,))
        response = self.client.post(url, self.rewritten_closed_data())
        self.assert_unchanged(self.victim_entry, before, response)
        self.assertEqual(attacker_before, self.snapshot(self.attacker_entry))
        self.assertEqual(count, Entry.no_join.count())

    def test_coworker_cannot_rewrite_unverified_active_entry(self):
        before = self.snapshot(self.victim_active)
        count = Entry.no_join.count()
        url = reverse('edit_entry', args=(self.victim_active.pk,))
        response = self.client.post(url, self.rewritten_active_data())
        self.assert_unchanged(self.victim_active, before, response)
        self.assertEqual(count, Entry.no_join.count())

    def test_second_lookup_cannot_write_a_different_entry(self):
        """A check against one row must not save a row loaded later by id.

        The first ``Entry.no_join.get`` runs as the application wrote it. A
        later ``get`` returns the victim row even if the caller asked for a
        different primary key, which is what a second lookup of the request
        id does when it is not the row that was authorized.
        """
        before = self.snapshot(self.victim_entry)
        attacker_before = self.snapshot(self.attacker_entry)
        count = Entry.no_join.count()
        data = self.rewritten_closed_data()
        original_get = Entry.no_join.get
        calls = []

        def get_then_swap(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return original_get(*args, **kwargs)
            return original_get(pk=self.victim_entry.pk)

        Entry.no_join.get = get_then_swap
        try:
            url = reverse('edit_entry', args=(self.victim_entry.pk,))
            response = self.client.post(url, data)
        finally:
            Entry.no_join.get = original_get

        self.assert_unchanged(self.victim_entry, before, response)
        self.assertEqual(attacker_before, self.snapshot(self.attacker_entry))
        self.assertEqual(count, Entry.no_join.count())

    def test_coworker_cannot_edit_verified_entry(self):
        before = self.snapshot(self.verified_entry)
        url = reverse('edit_entry', args=(self.verified_entry.pk,))
        response = self.client.post(url, self.rewritten_closed_data())
        self.assert_unchanged(self.verified_entry, before, response)

    def test_coworker_can_still_edit_own_unverified_entry(self):
        url = reverse('edit_entry', args=(self.attacker_entry.pk,))
        response = self.client.post(url, self.rewritten_closed_data())
        self.assertEqual(response.status_code, 302, response.status_code)
        stored = Entry.no_join.get(pk=self.attacker_entry.pk)
        self.assertEqual(stored.user_id, self.attacker.id)
        self.assertEqual(stored.project_id, self.other_project.id)
        self.assertEqual(stored.activity_id, self.other_activity.id)
        self.assertEqual(stored.location_id, self.other_location.id)
        self.assertEqual(stored.comments, 'rewritten by coworker')
        self.assertEqual(stored.seconds_paused, 120)
        self.assertEqual(stored.status, Entry.UNVERIFIED)
        self.assertGreater(stored.hours, 0)

    def test_payroll_user_can_edit_another_users_unverified_entry(self):
        self.client.logout()
        self.login_user(self.payroll)
        before_user = self.victim_entry.user_id
        url = reverse('edit_entry', args=(self.victim_entry.pk,))
        response = self.client.post(url, self.rewritten_closed_data())
        self.assertEqual(response.status_code, 302, response.status_code)
        stored = Entry.no_join.get(pk=self.victim_entry.pk)
        self.assertEqual(stored.user_id, before_user)
        self.assertEqual(stored.project_id, self.other_project.id)
        self.assertEqual(stored.activity_id, self.other_activity.id)
        self.assertEqual(stored.location_id, self.other_location.id)
        self.assertEqual(stored.comments, 'rewritten by coworker')
        self.assertEqual(stored.seconds_paused, 120)
        self.assertEqual(stored.status, Entry.UNVERIFIED)
        self.assertNotEqual(stored.hours, 0)

    def test_user_without_change_entry_cannot_edit(self):
        stranger = factories.User()
        self.client.logout()
        self.login_user(stranger)
        # The login form sets a CSRF cookie for any visitor. Django 1.4 compares
        # that token to the posted value and does not bind it to a permission.
        login_page = self.client.get(reverse('auth_login'))
        self.assertEqual(login_page.status_code, 200)
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        url = reverse('edit_entry', args=(self.victim_entry.pk,))
        response = self.client.get(url)
        self.assertRedirectsToLogin(response)
        before = self.snapshot(self.victim_entry)
        response = self.client.post(url, {
            'csrfmiddlewaretoken': token,
            'project': self.other_project.pk,
            'location': self.other_location.pk,
            'activity': self.other_activity.pk,
            'seconds_paused': 120,
            'comments': 'should not save',
            'start_time_0': '01/01/2013',
            'start_time_1': '09:00:00',
            'end_time_0': '01/01/2013',
            'end_time_1': '10:00:00',
        })
        self.assertRedirectsToLogin(response)
        self.assertEqual(before, self.snapshot(self.victim_entry))

from collections import namedtuple

from django.contrib.auth.models import User
from django.http import HttpResponse, HttpResponseForbidden
from django.utils.safestring import mark_safe

from selectable.base import LookupBase
from selectable.base import ModelLookup
from selectable.registry import registry

from timepiece.crm.models import Project, Business


class PermissionRequiredLookupMixin(object):
    """Restrict a lookup to active users who hold any of ``permissions``.

    django-selectable serves every registered lookup without authentication,
    so each lookup must refuse the request itself.
    """
    permissions = ()

    def has_permission(self, user):
        if user is None or not user.is_authenticated():
            return False
        return any(user.has_perm(perm) for perm in self.permissions)

    def results(self, request):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated():
            return HttpResponse(status=401)
        if not self.has_permission(user):
            return HttpResponseForbidden()
        return super(PermissionRequiredLookupMixin, self).results(request)

    def get_query(self, request, q):
        if not self.has_permission(getattr(request, 'user', None)):
            return self.empty_query()
        return super(PermissionRequiredLookupMixin, self).get_query(request, q)

    def empty_query(self):
        return []


class PermissionRequiredModelLookup(PermissionRequiredLookupMixin, ModelLookup):

    def empty_query(self):
        return self.get_queryset().none()


class ProjectLookup(PermissionRequiredModelLookup):
    model = Project
    search_fields = ('name__icontains', 'business__name__icontains',
            'business__short_name__icontains')
    # Project list, adding a project to a user, and the project reports.
    permissions = ('crm.view_project', 'crm.add_projectrelationship',
            'entries.view_entry_summary')

    def get_item_label(self, project):
        return mark_safe(u'<span class="project">%s</span>' %
                self.get_item_value(project))

    def get_item_value(self, project):
        return project.name if project else ''


class BusinessLookup(PermissionRequiredModelLookup):
    model = Business
    search_fields = ('name__icontains', 'short_name__icontains')
    # Business list, and choosing a business on the project form.
    permissions = ('crm.view_business', 'crm.add_project',
            'crm.change_project')

    def get_item_label(self, business):
        return mark_safe(u'<span class="business">%s</span>' %
                self.get_item_value(business))

    def get_item_value(self, business):
        return business.name if business else ''


class UserLookup(PermissionRequiredModelLookup):
    model = User
    # Email is deliberately not searchable, so a lookup cannot confirm
    # whether an address belongs to an account.
    search_fields = ('username__icontains', 'first_name__icontains',
            'last_name__icontains')
    # User list, and adding a user to a project.
    permissions = ('auth.view_user', 'crm.add_projectrelationship')

    def get_query(self, request, q):
        return super(UserLookup, self).get_query(request, q).order_by('last_name')

    def get_item_label(self, user):
        return mark_safe(u'<span class="user">%s</span>' %
                self.get_item_value(user))

    def get_item_value(self, user):
        return user.get_name_or_username() if user else ''


class QuickLookup(PermissionRequiredLookupMixin, LookupBase):
    # Quick search links to each result's detail page, so each result type
    # requires the permission for that page.
    lookup_permissions = {
        'user': 'auth.view_user',
        'project': 'crm.view_project',
        'business': 'crm.view_business',
    }
    permissions = tuple(lookup_permissions.values())

    def __init__(self, *args, **kwargs):
        self.lookups = {
            'user': UserLookup(),
            'project': ProjectLookup(),
            'business': BusinessLookup(),
        }
        super(QuickLookup, self).__init__(*args, **kwargs)

    def get_query(self, request, q):
        user = getattr(request, 'user', None)
        if not self.has_permission(user):
            return self.empty_query()

        results = []
        SearchResult = namedtuple('SearchResult', ['result_type', 'item', 'label', 'value'])

        for result_type, lookup in self.lookups.items():
            if not user.has_perm(self.lookup_permissions[result_type]):
                continue
            for item in lookup.get_query(request, q)[:10]:
                label = lookup.get_item_label(item)
                value = lookup.get_item_value(item)
                results.append(SearchResult(result_type, item, label, value))

        results.sort(lambda a, b: cmp(a.value, b.value))
        return results

    def get_item_label(self, item):
        return item.label

    def get_item_id(self, item):
        return '{0}-{1}'.format(item.result_type, item.item.pk)

    def get_item(self, value):
        try:
            result_type, pk = value.split('-', 1)
            return self.lookups[result_type].get_item(pk)
        except (ValueError, KeyError):
            return None

    def get_item_value(self, item):
        return item.value if item else ''


registry.register(BusinessLookup)
registry.register(ProjectLookup)
registry.register(UserLookup)
registry.register(QuickLookup)

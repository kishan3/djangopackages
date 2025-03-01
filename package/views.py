import importlib
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.urls import reverse
from django.db.models import Count, Q
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST


from grid.models import Grid
from homepage.models import Dpotw, Gotw
from package.forms import PackageForm, PackageExampleForm, DocumentationForm
from package.models import Category, Package, PackageExample
from package.repos import get_all_repos


def repo_data_for_js():
    repos = [handler.serialize() for handler in get_all_repos()]
    return json.dumps(repos)


def get_form_class(form_name):
    bits = form_name.split('.')
    form_module_name = '.'.join(bits[:-1])
    form_module = importlib.import_module(form_module_name)
    form_name = bits[-1]
    return getattr(form_module, form_name)


@login_required
def add_package(request, template_name="package/package_form.html"):

    if not request.user.profile.can_add_package:
        return HttpResponseForbidden("permission denied")

    new_package = Package()
    form = PackageForm(request.POST or None, instance=new_package)

    if form.is_valid():
        new_package = form.save()
        new_package.created_by = request.user
        new_package.last_modified_by = request.user
        new_package.save()
        #new_package.fetch_metadata()
        #new_package.fetch_commits()

        return HttpResponseRedirect(reverse("package", kwargs={"slug": new_package.slug}))

    return render(request, template_name, {
        "form": form,
        "repo_data": repo_data_for_js(),
        "action": "add",
        })


@login_required
def edit_package(request, slug, template_name="package/package_form.html"):

    if not request.user.profile.can_edit_package:
        return HttpResponseForbidden("permission denied")

    package = get_object_or_404(Package, slug=slug)
    form = PackageForm(request.POST or None, instance=package)

    if form.is_valid():
        modified_package = form.save()
        modified_package.last_modified_by = request.user
        modified_package.save()
        messages.add_message(request, messages.INFO, 'Package updated successfully')
        return HttpResponseRedirect(reverse("package", kwargs={"slug": modified_package.slug}))

    return render(request, template_name, {
        "form": form,
        "package": package,
        "repo_data": repo_data_for_js(),
        "action": "edit",
        })


@login_required
def update_package(request, slug):

    package = get_object_or_404(Package, slug=slug)
    package.fetch_metadata()
    package.fetch_commits()
    package.last_fetched = timezone.now()
    messages.add_message(request, messages.INFO, 'Package updated successfully')

    return HttpResponseRedirect(reverse("package", kwargs={"slug": package.slug}))


@login_required
def add_example(request, slug, template_name="package/add_example.html"):

    package = get_object_or_404(Package, slug=slug)
    new_package_example = PackageExample()
    form = PackageExampleForm(request.POST or None, instance=new_package_example)

    if form.is_valid():
        package_example = PackageExample(package=package,
                title=request.POST["title"],
                url=request.POST["url"],
                created_by=request.user)
        package_example.save()
        return HttpResponseRedirect(reverse("package", kwargs={"slug": package_example.package.slug}))

    return render(request, template_name, {
        "form": form,
        "package": package
        })


@login_required
def edit_example(request, slug, id, template_name="package/edit_example.html"):

    package_example = get_object_or_404(PackageExample, id=id)
    form = PackageExampleForm(request.POST or None, instance=package_example)

    if form.is_valid():
        form.save()
        return HttpResponseRedirect(reverse("package", kwargs={"slug": package_example.package.slug}))

    return render(request, template_name, {
        "form": form,
        "package_example": package_example
        })


@login_required
def delete_example(request, slug, id, template_name="package/delete_example.html"):

    package_example = get_object_or_404(PackageExample, id=id, package__slug__iexact=slug)
    if package_example.created_by is None and not request.user.is_staff:
        raise PermissionDenied
    if package_example.created_by.id != request.user.id and not request.user.is_staff:
        raise PermissionDenied

    return render(request, template_name, {
        "package_example": package_example
        })


@login_required
@require_POST
def confirm_delete_example(request, slug, id):

    package_example = get_object_or_404(PackageExample, id=id, package__slug__iexact=slug)
    if package_example.created_by.id != request.user.id and not request.user.is_staff:
        raise PermissionDenied

    package_example.delete()
    messages.add_message(request, messages.INFO, 'Package example successfully deleted.')

    return HttpResponseRedirect(reverse("package", kwargs={"slug": slug}))


def package_autocomplete(request):
    """
    Provides Package matching based on matches of the beginning
    """
    titles = []
    q = request.GET.get("q", "")
    if q:
        titles = (x.title for x in Package.objects.filter(title__istartswith=q))

    response = HttpResponse("\n".join(titles))

    setattr(response, "djangologging.suppress_output", True)
    return response


def category(request, slug, template_name="package/category.html"):
    category = get_object_or_404(Category, slug=slug)
    packages = category.package_set.select_related().annotate(usage_count=Count("usage")).order_by("-repo_watchers", "title")
    return render(request, template_name, {
        "category": category,
        "packages": packages,
        }
    )


def ajax_package_list(request, template_name="package/ajax_package_list.html"):
    q = request.GET.get("q", "")
    packages = []
    if q:
        _dash = f"{settings.PACKAGINATOR_SEARCH_PREFIX}-{q}"
        _space = f"{settings.PACKAGINATOR_SEARCH_PREFIX} {q}"
        _underscore = f'{settings.PACKAGINATOR_SEARCH_PREFIX}_{q}'
        packages = Package.objects.filter(
                        Q(title__istartswith=q) |
                        Q(title__istartswith=_dash) |
                        Q(title__istartswith=_space) |
                        Q(title__istartswith=_underscore)
                    )

    packages_already_added_list = []
    grid_slug = request.GET.get("grid", "")
    if packages and grid_slug:
        grids = Grid.objects.filter(slug=grid_slug)
        if grids:
            grid = grids[0]
            packages_already_added_list = [x['slug'] for x in grid.packages.all().values('slug')]
            new_packages = tuple(packages.exclude(slug__in=packages_already_added_list))[:20]
            number_of_packages = len(new_packages)
            if number_of_packages < 20:
                try:
                    old_packages = packages.filter(slug__in=packages_already_added_list)[:20 - number_of_packages]
                except AssertionError:
                    old_packages = None

                if old_packages:
                    old_packages = tuple(old_packages)
                    packages = new_packages + old_packages
            else:
                packages = new_packages

    return render(request, template_name, {
        "packages": packages,
        'packages_already_added_list': packages_already_added_list,
        }
    )


@login_required
def usage(request, slug, action):
    success = False
    package = get_object_or_404(Package, slug=slug)

    # Update the current user's usage of the given package as specified by the
    # request.
    if package.usage.filter(username=request.user.username):
        if action.lower() == 'add':
            # The user is already using the package
            success = True
            change = 0
        else:
            # If the action was not add and the user has already specified
            # they are a use the package then remove their usage.
            package.usage.remove(request.user)
            success = True
            change = -1
    else:
        if action.lower() == 'lower':
            # The user is not using the package
            success = True
            change = 0
        else:
            # If the action was not lower and the user is not already using
            # the package then add their usage.
            package.usage.add(request.user)
            success = True
            change = 1

    # Invalidate the cache of this users's used_packages_list.
    if change == 1 or change == -1:
        cache_key = "sitewide_used_packages_list_%s" % request.user.pk
        cache.delete(cache_key)
        package.grid_clear_detail_template_cache()

    # Return an ajax-appropriate response if necessary
    if request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        response = {'success': success}
        if success:
            response['change'] = change

        return HttpResponse(json.dumps(response))

    # Intelligently determine the URL to redirect the user to based on the
    # available information.
    next = request.GET.get('next') or request.headers.get('Referer') or reverse("package", kwargs={"slug": package.slug})
    return HttpResponseRedirect(next)


def python3_list(request, template_name="package/python3_list.html"):
    packages = Package.objects.filter(version__supports_python3=True).distinct()
    packages = packages.order_by("-pypi_downloads", "-repo_watchers", "title")

    values = "category, category_id, commit, commit_list, created, created_by, created_by_id, documentation_url, dpotw, grid, gridpackage, id, last_fetched, last_modified_by, last_modified_by_id, modified, packageexample, participants, pypi_downloads, pypi_url, repo_description, repo_forks, repo_url, repo_watchers, slug, title, usage, version".split(',')
    values = [x.strip() for x in values]
    if request.GET.get('sort') and request.GET.get('sort') not in values:
        # Some people have cached older versions of this view
        request.GET = request.GET.copy()
        del request.GET['sort']

    return render(
        request,
        template_name, {
            "packages": packages
        }
    )

def package_list(request, template_name="package/package_list.html"):

    categories = []
    for category in Category.objects.annotate(package_count=Count("package")):
        element = {
            "title": category.title,
            "description": category.description,
            "count": category.package_count,
            "slug": category.slug,
            "title_plural": category.title_plural,
            "show_pypi": category.show_pypi,
            "packages": category.package_set.annotate(usage_count=Count("usage")).order_by("-pypi_downloads", "-repo_watchers", "title")[:9]
        }
        categories.append(element)

    return render(
        request,
        template_name, {
            "categories": categories,
            "dpotw": Dpotw.objects.get_current(),
            "gotw": Gotw.objects.get_current(),
        }
    )


def package_detail(request, slug, template_name="package/package.html"):

    package = get_object_or_404(Package, slug=slug)
    no_development = package.no_development
    try:
        if package.category == Category.objects.get(slug='projects'):
            # projects get a bye because they are a website
            pypi_ancient = False
            pypi_no_release = False
        else:
            pypi_ancient = package.pypi_ancient
            pypi_no_release = package.pypi_ancient is None
        warnings = no_development or pypi_ancient or pypi_no_release
    except Category.DoesNotExist:
        pypi_ancient = False
        pypi_no_release = False
        warnings = no_development

    if request.GET.get("message"):
        messages.add_message(request, messages.INFO, request.GET.get("message"))

    return render(request, template_name,
            dict(
                package=package,
                pypi_ancient=pypi_ancient,
                no_development=no_development,
                pypi_no_release=pypi_no_release,
                warnings=warnings,
                latest_version=package.last_released(),
                repo=package.repo
            )
        )


def int_or_0(value):
    try:
        return int(value)
    except ValueError:
        return 0


@login_required
def post_data(request, slug):
    # if request.method == "POST":
        # try:
        #     # TODO Do this this with a form, really. Duh!
        #     package.repo_watchers = int_or_0(request.POST.get("repo_watchers"))
        #     package.repo_forks = int_or_0(request.POST.get("repo_forks"))
        #     package.repo_description = request.POST.get("repo_description")
        #     package.participants = request.POST.get('contributors')
        #     package.fetch_commits()  # also saves
        # except Exception as e:
        #     print e
    package = get_object_or_404(Package, slug=slug)
    package.fetch_pypi_data()
    package.repo.fetch_metadata(package)
    package.repo.fetch_commits(package)
    package.last_fetched = timezone.now()
    package.save()
    return HttpResponseRedirect(reverse("package", kwargs={"slug": package.slug}))


@login_required
def edit_documentation(request, slug, template_name="package/documentation_form.html"):
    package = get_object_or_404(Package, slug=slug)
    form = DocumentationForm(request.POST or None, instance=package)
    if form.is_valid():
        form.save()
        messages.add_message(request, messages.INFO, 'Package documentation updated successfully')
        return redirect(package)
    return render(request, template_name,
            dict(
                package=package,
                form=form
            )
        )


@csrf_exempt
def github_webhook(request):
    if request.method == "POST":
        data = json.loads(request.POST['payload'])

        # Webhook Test
        if "zen" in data:
            return HttpResponse(data['hook_id'])

        repo_url = data['repository']['url']

        # service test
        if repo_url == "http://github.com/mojombo/grit":
            return HttpResponse("Service Test pass")

        package = get_object_or_404(Package, repo_url=repo_url)
        package.repo.fetch_commits(package)
        package.last_fetched = timezone.now()
        package.save()
    return HttpResponse()

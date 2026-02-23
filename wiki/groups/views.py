from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.shortcuts import get_object_or_404, redirect, render

from wiki.lib.permissions import is_system_owner

from .forms import AddMemberForm, GroupForm


def _can_manage_groups(user):
    """Check if user can create/edit/delete groups and manage members."""
    return user.is_staff or is_system_owner(user)


@login_required
def group_list(request):
    """List all groups with member counts."""
    groups = Group.objects.prefetch_related("user_set").order_by("name")
    return render(
        request,
        "groups/list.html",
        {"groups": groups, "can_manage": _can_manage_groups(request.user)},
    )


@login_required
def group_create(request):
    """Create a new group."""
    if not _can_manage_groups(request.user):
        messages.error(request, "You don't have permission to create groups.")
        return redirect("group_list")

    form = GroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"]
        if Group.objects.filter(name=name).exists():
            messages.error(request, f'A group named "{name}" already exists.')
        else:
            group = Group.objects.create(name=name)
            messages.success(request, f'Group "{name}" created.')
            return redirect("group_detail", pk=group.pk)

    return render(
        request, "groups/form.html", {"form": form, "creating": True}
    )


@login_required
def group_detail(request, pk):
    """Show group members with add/remove forms."""
    group = get_object_or_404(Group, pk=pk)
    members = group.user_set.select_related("profile").order_by("email")
    form = AddMemberForm()
    can_manage = _can_manage_groups(request.user)
    return render(
        request,
        "groups/detail.html",
        {
            "group": group,
            "members": members,
            "form": form,
            "can_manage": can_manage,
        },
    )


@login_required
def group_edit(request, pk):
    """Edit group name."""
    group = get_object_or_404(Group, pk=pk)
    if not _can_manage_groups(request.user):
        messages.error(request, "You don't have permission to edit groups.")
        return redirect("group_detail", pk=pk)

    form = GroupForm(request.POST or None, initial={"name": group.name})
    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"]
        if Group.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f'A group named "{name}" already exists.')
        else:
            group.name = name
            group.save()
            messages.success(request, "Group updated.")
            return redirect("group_detail", pk=pk)

    return render(
        request,
        "groups/form.html",
        {"form": form, "creating": False, "group": group},
    )


@login_required
def group_delete(request, pk):
    """Delete a group after confirmation."""
    group = get_object_or_404(Group, pk=pk)
    if not _can_manage_groups(request.user):
        messages.error(request, "You don't have permission to delete groups.")
        return redirect("group_detail", pk=pk)

    if request.method == "POST":
        name = group.name
        group.delete()
        messages.success(request, f'Group "{name}" deleted.')
        return redirect("group_list")

    return render(request, "groups/delete_confirm.html", {"group": group})


@login_required
def group_add_member(request, pk):
    """Add a user to the group by email."""
    group = get_object_or_404(Group, pk=pk)
    if not _can_manage_groups(request.user):
        messages.error(
            request, "You don't have permission to manage group members."
        )
        return redirect("group_detail", pk=pk)

    if request.method == "POST":
        form = AddMemberForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"].strip()
            user = User.objects.filter(
                email__istartswith=username + "@"
            ).first()
            if not user:
                messages.error(
                    request,
                    f'No user found with username "{username}".',
                )
            elif group.user_set.filter(pk=user.pk).exists():
                messages.info(
                    request,
                    f"{username} is already a member.",
                )
            else:
                user.groups.add(group)
                messages.success(
                    request,
                    f"Added {username} to the group.",
                )

    return redirect("group_detail", pk=pk)


@login_required
def group_remove_member(request, pk):
    """Remove a user from the group."""
    group = get_object_or_404(Group, pk=pk)
    if not _can_manage_groups(request.user):
        messages.error(
            request, "You don't have permission to manage group members."
        )
        return redirect("group_detail", pk=pk)

    if request.method == "POST":
        user_id = request.POST.get("user_id")
        user = User.objects.filter(pk=user_id).first()
        if user:
            user.groups.remove(group)
            messages.success(request, "Member removed.")

    return redirect("group_detail", pk=pk)

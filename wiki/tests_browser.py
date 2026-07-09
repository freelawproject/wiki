"""Browser tests for interactive UI components.

Uses Playwright + Django LiveServer to test JavaScript-dependent behavior
that can't be verified with the Django test client alone.

Run with: pytest wiki/tests_browser.py -v
"""

import os

import pytest

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from wiki.directories.models import Directory
from wiki.pages.models import Page as WikiPage
from wiki.pages.models import PageRevision
from wiki.users.models import UserProfile


@pytest.fixture
def browser_page():
    """A Playwright browser page (avoids conftest 'page' collision)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pw_page = browser.new_page()
        yield pw_page
        browser.close()


@pytest.fixture
def browser_user(db):
    """User with a known password for browser login."""
    u = User.objects.create_user(
        username="playwright@free.law",
        email="playwright@free.law",
        password="testpass123",
    )
    UserProfile.objects.create(user=u, display_name="Playwright")
    u.is_staff = True
    u.save()
    return u


@pytest.fixture
def dir_tree(browser_user):
    """Root + child directories with different visibility settings."""
    root = Directory.objects.create(path="", title="Home")
    Directory.objects.create(
        path="staff",
        title="Staff",
        parent=root,
        owner=browser_user,
        created_by=browser_user,
        visibility=Directory.Visibility.INTERNAL,
    )
    Directory.objects.create(
        path="docs",
        title="Docs",
        parent=root,
        owner=browser_user,
        created_by=browser_user,
        visibility=Directory.Visibility.PUBLIC,
    )
    return root


@pytest.fixture
def sample_page(browser_user, dir_tree):
    """A page inside the 'staff' directory."""
    staff_dir = Directory.objects.get(path="staff")
    p = WikiPage.objects.create(
        title="Staff Guide",
        slug="staff-guide",
        content="Internal info.",
        directory=staff_dir,
        owner=browser_user,
        created_by=browser_user,
        updated_by=browser_user,
    )
    PageRevision.objects.create(
        page=p,
        title=p.title,
        content=p.content,
        change_message="Initial creation",
        revision_number=1,
        created_by=browser_user,
    )
    return p


def _force_login(browser_page, live_server, user):
    """Log in by setting the session cookie via Django test client."""
    client = Client()
    client.force_login(user)
    cookie = client.cookies["sessionid"]

    browser_page.goto(live_server.url)
    browser_page.context.add_cookies(
        [
            {
                "name": "sessionid",
                "value": cookie.value,
                "domain": "localhost",
                "path": "/",
            }
        ]
    )


def _get_visible_option_labels(listbox):
    """Collect the display text of all visible options in a listbox."""
    options = listbox.locator("[role='option']")
    texts = []
    for i in range(options.count()):
        opt = options.nth(i)
        if not opt.is_visible():
            continue
        label = opt.locator(".text-sm.font-medium")
        if label.count() > 0:
            texts.append(label.text_content().strip())
        else:
            texts.append(opt.text_content().strip())
    return texts


@pytest.mark.django_db(transaction=True)
class TestInheritSelectDropdown:
    """Verify that inherit-select dropdowns render correctly."""

    def test_directory_edit_no_duplicate_options(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """On directory edit, the inherited value should not appear
        as both the inherit option and an explicit option."""
        _force_login(browser_page, live_server, browser_user)

        url = reverse("directory_edit", kwargs={"path": "staff"})
        browser_page.goto(f"{live_server.url}{url}")

        # Open the visibility dropdown
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        vis_button.click()

        listbox = browser_page.locator("#listbox_visibility")
        texts = _get_visible_option_labels(listbox)

        # The parent (Home) has visibility "Public". The inherit option
        # shows "Public / Provided by Home". The explicit "Public"
        # option should be hidden to avoid duplication.
        assert texts.count("Public") == 1, (
            f"Expected 'Public' once, got {texts}"
        )

    def test_directory_edit_explicit_matching_inherited(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When a directory has explicit visibility='public' and
        the parent also has 'public', the dropdown should show:
        - 'Public / Provided by Home' (inherit option)
        - 'Staff'
        - 'Private'
        NOT a separate 'Public' explicit option (it's redundant)."""
        _force_login(browser_page, live_server, browser_user)

        url = reverse("directory_edit", kwargs={"path": "docs"})
        browser_page.goto(f"{live_server.url}{url}")

        # Button should show "Public" (proper label, not raw "public")
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_contain_text("Public")

        # Open the dropdown
        vis_button.click()
        listbox = browser_page.locator("#listbox_visibility")
        texts = _get_visible_option_labels(listbox)

        # Should be exactly 3 options, with "Public" appearing once
        assert texts == ["Public", "Staff", "Private"], (
            f"Expected ['Public', 'Staff', 'Private'], got {texts}"
        )

    def test_new_page_in_dir_uses_inherit_select_on_load(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When creating a page within a directory (e.g. /c/staff/new/),
        the form should use inherit-select components on initial load,
        not plain <select> elements."""
        _force_login(browser_page, live_server, browser_user)

        url = reverse("page_create_in_dir", kwargs={"path": "staff"})
        browser_page.goto(f"{live_server.url}{url}")

        # Should NOT have a plain <select> for visibility
        plain_select = browser_page.locator("select[name='visibility']")
        assert plain_select.count() == 0, (
            "Expected inherit-select, got plain <select>"
        )

        # Should have the inherit-select Alpine component
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_be_visible()
        expect(vis_button).to_contain_text("Staff")

    def test_new_page_selects_upgrade_on_dir_pick(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """On /c/new/, plain <select> fields should upgrade to
        inherit-select components when a directory is picked."""
        _force_login(browser_page, live_server, browser_user)

        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        # Initially should be a plain <select>
        plain_select = browser_page.locator("select[name='visibility']")
        assert plain_select.count() == 1

        # Pick the "Staff" directory (internal visibility)
        location_input = browser_page.locator("#location-input")
        location_input.click()
        with browser_page.expect_response("**/api/dir-inherit/**"):
            browser_page.locator("#dir-dropdown").locator("text=Staff").click()

        # Plain select should be gone, replaced by inherit-select
        assert plain_select.count() == 0
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_be_visible()
        expect(vis_button).to_contain_text("Staff")

    def test_page_form_inherit_select_updates_on_dir_change(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When the user changes the directory in the location picker,
        the inherit dropdowns should update to reflect the new
        directory's inherited values."""
        _force_login(browser_page, live_server, browser_user)

        # Start creating a page in "Staff" (internal visibility)
        url = reverse("page_create_in_dir", kwargs={"path": "staff"})
        browser_page.goto(f"{live_server.url}{url}")

        # The visibility button should show "Staff"
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_contain_text("Staff")

        # Backspace to remove "Staff" and pick "Docs" (public).
        location_input = browser_page.locator("#location-input")
        location_input.click()
        with browser_page.expect_response("**/api/dir-search/**"):
            location_input.press("Backspace")
        # Wait for the dropdown to have the "Docs" item, then select
        # it via JS to avoid race conditions with dropdown rebuilds.
        browser_page.wait_for_function("""
            () => document.querySelector('#dir-dropdown [data-title="Docs"]')
        """)
        browser_page.evaluate("""() => {
            var el = document.querySelector('#dir-dropdown [data-title="Docs"]');
            if (el) el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
        }""")

        # The visibility button should update to show "Public"
        expect(vis_button).to_contain_text("Public", timeout=10000)

    def test_page_form_no_duplicate_after_dir_change(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """After changing directory, the dropdown options should not
        contain duplicate data-value attributes."""
        _force_login(browser_page, live_server, browser_user)

        # Start in "Staff" dir, then switch to "Docs"
        url = reverse("page_create_in_dir", kwargs={"path": "staff"})
        browser_page.goto(f"{live_server.url}{url}")

        location_input = browser_page.locator("#location-input")
        location_input.click()
        with browser_page.expect_response("**/api/dir-search/**"):
            location_input.press("Backspace")
        # Use JS dispatch to avoid race conditions with dropdown rebuilds
        # (same pattern as test_page_form_inherit_select_updates_on_dir_change)
        browser_page.wait_for_function("""
            () => document.querySelector('#dir-dropdown [data-title="Docs"]')
        """)
        with browser_page.expect_response("**/api/dir-inherit/**"):
            browser_page.evaluate("""() => {
                var el = document.querySelector('#dir-dropdown [data-title="Docs"]');
                if (el) el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            }""")

        # Verify the button updated (inherit resolved to "Public")
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_contain_text("Public")

        # Check data-value attributes for duplicates (no need to
        # open the dropdown — just inspect the DOM directly)
        options = browser_page.locator("#listbox_visibility [role='option']")
        values = []
        for i in range(options.count()):
            val = options.nth(i).get_attribute("data-value")
            values.append(val)
        assert len(values) == len(set(values)), (
            f"Duplicate data-value in options: {values}"
        )
        # "public" should not appear as an explicit option since it
        # matches the inherited value
        assert "public" not in values, (
            f"Explicit 'public' should be filtered, got: {values}"
        )


@pytest.mark.django_db(transaction=True)
class TestLocationPickerKeyboard:
    """Verify arrow key navigation in the location picker dropdown."""

    def test_arrow_keys_highlight_items(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """Arrow keys should move the highlight through dropdown items."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        location_input = browser_page.locator("#location-input")
        location_input.click()

        # Wait for dropdown to appear
        dropdown = browser_page.locator("#dir-dropdown")
        dropdown.locator("[data-path]").first.wait_for(state="visible")

        items = dropdown.locator("[data-path], [data-new]")
        count = items.count()
        assert count >= 2, f"Need at least 2 items, got {count}"

        # First item should be highlighted by default
        first = items.nth(0)
        assert "bg-gray-100" in first.get_attribute("class")

        # Arrow down to second item
        location_input.press("ArrowDown")
        second = items.nth(1)
        assert "bg-gray-100" in second.get_attribute("class")
        assert "bg-gray-100" not in first.get_attribute("class")

        # Arrow up back to first
        location_input.press("ArrowUp")
        assert "bg-gray-100" in first.get_attribute("class")
        assert "bg-gray-100" not in second.get_attribute("class")

    def test_enter_selects_highlighted_item(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """Enter should select the currently highlighted item."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        location_input = browser_page.locator("#location-input")
        location_input.click()

        dropdown = browser_page.locator("#dir-dropdown")
        dropdown.locator("[data-path]").first.wait_for(state="visible")

        # Get the first item's title before selecting
        first_title = (
            dropdown.locator("[data-path], [data-new]")
            .first.text_content()
            .strip()
        )

        # Press Enter to select the first (default highlighted) item
        location_input.press("Enter")

        # The location chips should now contain the selected directory
        chips = browser_page.locator("#location-chips")
        expect(chips).to_contain_text(first_title)


@pytest.mark.django_db(transaction=True)
class TestPageCreateFromRoot:
    """Test page creation from /c/new/ using the location picker.

    Regression tests for a bug where selecting a directory via the
    location picker caused silent form validation failure because
    'inherit' was not a valid choice when starting from root level.
    """

    def test_create_page_in_new_subdirectory(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """From /c/new/, pick an existing dir, create a new subdir,
        fill the form, and verify the page is created."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        location_input = browser_page.locator("#location-input")
        dropdown = browser_page.locator("#dir-dropdown")

        # Step 1: Select existing "Docs" directory
        location_input.click()
        dropdown.locator("[data-path]").first.wait_for(state="visible")
        with browser_page.expect_response("**/api/dir-inherit/**"):
            dropdown.locator("text=Docs").click()

        # Step 2: Type a new directory name and press Tab to create it
        location_input.fill("Operations")
        dropdown.locator("[data-new]").wait_for(state="visible")
        location_input.press("Tab")

        # Verify both segments appear as chips
        chips = browser_page.locator("#location-chips")
        expect(chips).to_contain_text("Docs")
        expect(chips).to_contain_text("Operations")

        # Step 3: Fill in the form
        browser_page.locator("#id_title").fill("Ops Runbook")
        browser_page.locator("#id_change_message").clear()
        browser_page.locator("#id_change_message").fill("Add ops runbook")

        # Step 4: Submit
        browser_page.get_by_role("button", name="Create Page").click()

        # Should redirect to the new page
        expected = reverse(
            "resolve_path",
            kwargs={"path": "docs/operations/ops-runbook"},
        )
        browser_page.wait_for_url(f"**{expected}")
        expect(browser_page.locator("h1")).to_contain_text("Ops Runbook")

        # Verify directory was created
        assert Directory.objects.filter(path="docs/operations").exists()

    def test_create_page_selecting_existing_directory(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """From /c/new/, pick an existing directory and submit.
        Inherit fields (in_sitemap, in_llms_txt) should be accepted."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        location_input = browser_page.locator("#location-input")
        dropdown = browser_page.locator("#dir-dropdown")

        # Select existing "Docs" directory
        location_input.click()
        dropdown.locator("[data-path]").first.wait_for(state="visible")
        with browser_page.expect_response("**/api/dir-inherit/**"):
            dropdown.locator("text=Docs").click()

        # Fill in the form
        browser_page.locator("#id_title").fill("Quick Start")
        browser_page.locator("#id_change_message").clear()
        browser_page.locator("#id_change_message").fill("Add guide")

        # Submit — in_sitemap and in_llms_txt stay "inherit"
        browser_page.get_by_role("button", name="Create Page").click()

        # Should redirect to the new page
        expected = reverse("resolve_path", kwargs={"path": "docs/quick-start"})
        browser_page.wait_for_url(f"**{expected}")
        expect(browser_page.locator("h1")).to_contain_text("Quick Start")

    def test_validation_error_preserves_location_picker(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When form validation fails, the location picker should
        preserve the selected directory."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        location_input = browser_page.locator("#location-input")
        dropdown = browser_page.locator("#dir-dropdown")

        # Select "Staff" directory
        location_input.click()
        dropdown.locator("[data-path]").first.wait_for(state="visible")
        with browser_page.expect_response("**/api/dir-inherit/**"):
            dropdown.locator("text=Staff").click()

        # Leave title empty (triggers validation error)
        browser_page.locator("#id_change_message").clear()
        browser_page.locator("#id_change_message").fill("Test")

        # Submit — should fail
        browser_page.get_by_role("button", name="Create Page").click()
        browser_page.wait_for_load_state("networkidle")

        # Location picker should still show "Staff"
        chips = browser_page.locator("#location-chips")
        expect(chips).to_contain_text("Staff")


@pytest.fixture
def wiki_link_pages(browser_user, dir_tree):
    """A pair of pages whose titles share a prefix, for autocomplete tests.

    'Staff Guide' lives in /staff (from dir_tree), 'Stations' at root.
    A query for "sta" matches both; "stat" matches only Stations.
    """
    staff_dir = Directory.objects.get(path="staff")
    staff_guide = WikiPage.objects.create(
        title="Staff Guide",
        slug="staff-guide",
        content="Internal info.",
        directory=staff_dir,
        owner=browser_user,
        created_by=browser_user,
        updated_by=browser_user,
    )
    PageRevision.objects.create(
        page=staff_guide,
        title=staff_guide.title,
        content=staff_guide.content,
        change_message="Initial",
        revision_number=1,
        created_by=browser_user,
    )
    stations = WikiPage.objects.create(
        title="Stations",
        slug="stations",
        content="Public list.",
        owner=browser_user,
        created_by=browser_user,
        updated_by=browser_user,
    )
    PageRevision.objects.create(
        page=stations,
        title=stations.title,
        content=stations.content,
        change_message="Initial",
        revision_number=1,
        created_by=browser_user,
    )
    return staff_guide, stations


def _focus_editor(browser_page):
    """Focus the CodeMirror editor on the page-create form."""
    cm = browser_page.locator(".CodeMirror textarea").first
    cm.focus()
    return cm


@pytest.mark.django_db(transaction=True)
class TestWikiLinkAutocomplete:
    """The #wiki-link dropdown must react to every user edit, not just
    insertions, and must not reopen itself after the user picks a suggestion."""

    def test_backspace_hides_dropdown_when_query_too_short(
        self, browser_page, live_server, browser_user, wiki_link_pages
    ):
        """Typing #sta shows matches; backspacing to #s should hide the
        dropdown (query under the 2-char threshold). Regression guard
        against the bug where deletion didn't fire the refresh at all."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")
        _focus_editor(browser_page)
        dropdown = browser_page.locator("#slug-dropdown")

        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("#sta")
        dropdown.locator("[data-path]").first.wait_for(state="visible")

        browser_page.keyboard.press("Backspace")
        browser_page.keyboard.press("Backspace")
        expect(dropdown).to_be_hidden()

    def test_backspace_refreshes_results_when_query_still_valid(
        self, browser_page, live_server, browser_user, wiki_link_pages
    ):
        """Typing #stat matches only 'Stations'; backspacing to #sta should
        fire a new search and include 'Staff Guide' in the results. Regression
        guard against the dropdown showing stale matches from the longer query."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")
        _focus_editor(browser_page)
        dropdown = browser_page.locator("#slug-dropdown")

        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("#stat")
        dropdown.locator("[data-path]").first.wait_for(state="visible")
        # Only "Stations" matches "stat"
        expect(dropdown).to_contain_text("Stations")
        expect(dropdown).not_to_contain_text("Staff Guide")

        # Backspace one char — query is now "sta", should re-query and
        # pick up the broader match set.
        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.press("Backspace")
        expect(dropdown).to_contain_text("Staff Guide")
        expect(dropdown).to_contain_text("Stations")

    def test_selection_does_not_reopen_dropdown(
        self, browser_page, live_server, browser_user, wiki_link_pages
    ):
        """Picking an item inserts the qualified path and closes the
        dropdown. Regression guard against the `change` handler reopening
        the dropdown right after the programmatic insert."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")
        _focus_editor(browser_page)
        dropdown = browser_page.locator("#slug-dropdown")

        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("#staf")
        dropdown.locator("[data-path]").first.wait_for(state="visible")

        # Enter picks the highlighted item (first by default)
        browser_page.keyboard.press("Enter")
        expect(dropdown).to_be_hidden()
        # Give any lingering change handler a chance to fire
        browser_page.wait_for_timeout(250)
        expect(dropdown).to_be_hidden()

    def test_selection_inserts_qualified_path(
        self, browser_page, live_server, browser_user, wiki_link_pages
    ):
        """Picker inserts the full #dir/slug, not just #slug — so
        references stay unambiguous even once sibling slugs collide."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")
        _focus_editor(browser_page)
        dropdown = browser_page.locator("#slug-dropdown")

        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("#staff g")
        # The search uses the segment after the last '/' — "staff g" is one
        # segment and matches "Staff Guide". Wait for results.
        dropdown.locator("[data-path]").first.wait_for(state="visible")
        browser_page.keyboard.press("Enter")

        # The editor should now contain the qualified path
        body = browser_page.locator(".CodeMirror").first.text_content()
        assert "#staff/staff-guide" in body

    def test_escape_hides_dropdown(
        self, browser_page, live_server, browser_user, wiki_link_pages
    ):
        """Escape closes the dropdown even with a matching query, and
        typing another character re-opens it (not stuck dismissed)."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")
        _focus_editor(browser_page)
        dropdown = browser_page.locator("#slug-dropdown")

        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("#sta")
        dropdown.locator("[data-path]").first.wait_for(state="visible")

        browser_page.keyboard.press("Escape")
        expect(dropdown).to_be_hidden()

        # Typing more chars should reopen the dropdown
        with browser_page.expect_response("**/api/page-search/**"):
            browser_page.keyboard.type("f")
        dropdown.locator("[data-path]").first.wait_for(state="visible")


# ── Tabbed code blocks ({% tabs %}) ──────────────────────────────────

_TABS_GROUP_FULL = (
    "{% tabs %}\n\n"
    "```curl\ncurl -L https://example.com/api/\n```\n\n"
    "```python\nimport requests\n```\n\n"
    "```javascript\nawait fetch(url)\n```\n\n"
    "{% endtabs %}"
)
_TABS_GROUP_SHORT = (
    "{% tabs %}\n\n"
    "```curl\ncurl -X POST https://example.com/api/\n```\n\n"
    "```python\nimport httpx\n```\n\n"
    "{% endtabs %}"
)


@pytest.fixture
def tabbed_pages(browser_user, dir_tree):
    """Two pages with tabbed code groups in the public docs directory."""
    docs = Directory.objects.get(path="docs")

    def make(slug, title, content):
        p = WikiPage.objects.create(
            title=title,
            slug=slug,
            content=content,
            directory=docs,
            owner=browser_user,
            created_by=browser_user,
            updated_by=browser_user,
        )
        PageRevision.objects.create(
            page=p,
            title=p.title,
            content=p.content,
            change_message="Initial creation",
            revision_number=1,
            created_by=browser_user,
        )
        return p

    first = make(
        "api-examples",
        "API Examples",
        f"Intro.\n\n{_TABS_GROUP_FULL}\n\nMiddle.\n\n{_TABS_GROUP_SHORT}\n",
    )
    second = make("more-examples", "More Examples", _TABS_GROUP_FULL)
    return first, second


@pytest.mark.django_db(transaction=True)
class TestCodeTabs:
    """Tabbed code groups: labels, cross-group sync, persistence, copy."""

    def _goto(self, browser_page, live_server, wiki_page):
        url = reverse("resolve_path", kwargs={"path": wiki_page.content_path})
        browser_page.goto(f"{live_server.url}{url}")

    def test_labels_and_default_selection(
        self, browser_page, live_server, browser_user, tabbed_pages
    ):
        _force_login(browser_page, live_server, browser_user)
        self._goto(browser_page, live_server, tabbed_pages[0])

        groups = browser_page.locator(".code-tabs")
        expect(groups).to_have_count(2)
        first_tabs = groups.nth(0).locator("[role='tab']")
        expect(first_tabs).to_have_text(["cURL", "Python", "JavaScript"])
        expect(first_tabs.nth(0)).to_have_attribute("aria-selected", "true")

        panels = groups.nth(0).locator(".code-block-wrapper")
        expect(panels.nth(0)).to_be_visible()
        expect(panels.nth(1)).to_be_hidden()
        expect(panels.nth(2)).to_be_hidden()

    def test_click_syncs_all_groups(
        self, browser_page, live_server, browser_user, tabbed_pages
    ):
        _force_login(browser_page, live_server, browser_user)
        self._goto(browser_page, live_server, tabbed_pages[0])

        groups = browser_page.locator(".code-tabs")
        groups.nth(0).get_by_role("tab", name="Python").click()

        # Both groups switch to Python
        expect(
            groups.nth(0).get_by_role("tab", name="Python")
        ).to_have_attribute("aria-selected", "true")
        expect(
            groups.nth(1).get_by_role("tab", name="Python")
        ).to_have_attribute("aria-selected", "true")
        expect(
            groups.nth(1).locator(".code-block-wrapper").nth(0)
        ).to_be_hidden()
        expect(
            groups.nth(1).locator(".code-block-wrapper").nth(1)
        ).to_be_visible()

    def test_selection_persists_across_pages(
        self, browser_page, live_server, browser_user, tabbed_pages
    ):
        _force_login(browser_page, live_server, browser_user)
        self._goto(browser_page, live_server, tabbed_pages[0])

        browser_page.locator(".code-tabs").nth(0).get_by_role(
            "tab", name="JavaScript"
        ).click()

        self._goto(browser_page, live_server, tabbed_pages[1])
        group = browser_page.locator(".code-tabs").nth(0)
        expect(group.get_by_role("tab", name="JavaScript")).to_have_attribute(
            "aria-selected", "true"
        )
        expect(group.locator(".code-block-wrapper").nth(2)).to_be_visible()

    def test_tabs_render_in_editor_preview(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """The editor's Preview tab enhances injected HTML, so tab groups
        get their tab bar there too — not just on detail views."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}{reverse('page_create')}")

        browser_page.wait_for_selector(".CodeMirror")
        browser_page.evaluate(
            "(content) => document.querySelector('.CodeMirror')"
            ".CodeMirror.setValue(content)",
            _TABS_GROUP_FULL,
        )
        with browser_page.expect_response("**/api/preview/**"):
            browser_page.locator(".editor-tab[data-tab='preview']").click()

        preview = browser_page.locator("#tab-preview-content")
        expect(preview.locator(".code-tabs-bar")).to_be_visible()
        tabs = preview.locator("[role='tab']")
        expect(tabs).to_have_text(["cURL", "Python", "JavaScript"])
        expect(tabs.nth(0)).to_have_attribute("aria-selected", "true")

    def test_copy_button_copies_active_tab(
        self, browser_page, live_server, browser_user, tabbed_pages
    ):
        browser_page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"]
        )
        _force_login(browser_page, live_server, browser_user)
        self._goto(browser_page, live_server, tabbed_pages[1])

        group = browser_page.locator(".code-tabs").nth(0)
        group.get_by_role("tab", name="Python").click()
        group.locator(
            ".code-block-wrapper:not([hidden]) .copy-code-btn"
        ).click()

        clipboard = browser_page.evaluate(
            "() => navigator.clipboard.readText()"
        )
        assert "import requests" in clipboard

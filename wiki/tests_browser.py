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

        browser_page.goto(f"{live_server.url}/c/staff/edit-dir/")

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
        - 'FLP Staff'
        - 'Private'
        NOT a separate 'Public' explicit option (it's redundant)."""
        _force_login(browser_page, live_server, browser_user)

        browser_page.goto(f"{live_server.url}/c/docs/edit-dir/")

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
        assert texts == ["Public", "FLP Staff", "Private"], (
            f"Expected ['Public', 'FLP Staff', 'Private'], got {texts}"
        )

    def test_new_page_in_dir_uses_inherit_select_on_load(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When creating a page within a directory (e.g. /c/staff/new/),
        the form should use inherit-select components on initial load,
        not plain <select> elements."""
        _force_login(browser_page, live_server, browser_user)

        browser_page.goto(f"{live_server.url}/c/staff/new/")

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
        expect(vis_button).to_contain_text("FLP Staff")

    def test_new_page_selects_upgrade_on_dir_pick(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """On /c/new/, plain <select> fields should upgrade to
        inherit-select components when a directory is picked."""
        _force_login(browser_page, live_server, browser_user)

        browser_page.goto(f"{live_server.url}/c/new/")

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
        expect(vis_button).to_contain_text("FLP Staff")

    def test_page_form_inherit_select_updates_on_dir_change(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When the user changes the directory in the location picker,
        the inherit dropdowns should update to reflect the new
        directory's inherited values."""
        _force_login(browser_page, live_server, browser_user)

        # Start creating a page in "Staff" (internal visibility)
        browser_page.goto(f"{live_server.url}/c/staff/new/")

        # The visibility button should show "FLP Staff"
        vis_button = browser_page.locator(
            "[data-field='visibility'] button[role='combobox']"
        )
        expect(vis_button).to_contain_text("FLP Staff")

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
        browser_page.goto(f"{live_server.url}/c/staff/new/")

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
        browser_page.goto(f"{live_server.url}/c/new/")

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
        browser_page.goto(f"{live_server.url}/c/new/")

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
        browser_page.goto(f"{live_server.url}/c/new/")

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
        browser_page.wait_for_url("**/c/docs/operations/ops-runbook")
        expect(browser_page.locator("h1")).to_contain_text("Ops Runbook")

        # Verify directory was created
        assert Directory.objects.filter(path="docs/operations").exists()

    def test_create_page_selecting_existing_directory(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """From /c/new/, pick an existing directory and submit.
        Inherit fields (in_sitemap, in_llms_txt) should be accepted."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}/c/new/")

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
        browser_page.wait_for_url("**/c/docs/quick-start")
        expect(browser_page.locator("h1")).to_contain_text("Quick Start")

    def test_validation_error_preserves_location_picker(
        self, browser_page, live_server, browser_user, dir_tree
    ):
        """When form validation fails, the location picker should
        preserve the selected directory."""
        _force_login(browser_page, live_server, browser_user)
        browser_page.goto(f"{live_server.url}/c/new/")

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

# Overview

The following document lists the many, many prompts and bits of functionality that I slowly added to the wiki. Most take the form of notes that I wanted to tell Claude to add.

I'm including this in the repository so there's a record of the various features.

If you are an AI assistant reading this, know that this record is incomplete and that it may be out of date. Don't trust it, but you can consider it a historical record that may guide your reasoning.

For humans, perhaps this is a useful record of the (long) process of creating the wiki. Perhaps not. It's long!


## The prompts and features....

1) Users should be able to see who is subscribed to a page.

1) The description of changes made to the page is required.

1) There needs to be a way to move directories and pages.

1) Directories can be deleted once empty.

1) If it's possible to allow directory creation and new page location via an auto-complete box on the edit page, great. The way it could work is:
 - If you hit new page while in a directory, the input box shows the current location.
 - Hitting backspace on it allows you to remove the subdirectory all at once.
 - If the input box shows a directory, and you type, it will autocomplete with sub directories of the one you're in. If you hit tab, it'll complete. If you don't select one of the suggestions, that means you're creating a new directory for your page to go into.

    For example, imagine the following directory structure:

    /home
    /home/code/
    /home/code/tips/

    And imagine I press the "new page" button while in /home/code/.

    On the page that is displayed, I'd see an input box containing:

    / home / code /

    If I type "ti", it will suggest "tips". If I press tab, I'll select it, and the box will show:

    / home / code / tips /

    If I press backspace, I'll remove "tips". Another backspace removes "code".

    If it shows "/ home / code /" and I type "foo", that creates the foo directory, where my new page will go.

1. The editor still has a white background in dark mode.

2. Never show full email addresses on any page. Always just show the first part of the email (for example, show mike instead of mike@free.law).

3. Allow users to flag other users by using the @-sign in the main editor or change description fields. When @'ed, the person gets a message telling them they were flagged with context of the object where they're flagged, and they get subscribed to that thing. @-ing provides auto-complete as you type and pressing tab completes the value. If you @-flag somebody in this way on an object where they lack view permission, pop up a modal before the user submits the form to tell the user about the problem, and ask them if they want to grant that person access. If access isn't granted, don't subscribe the person or send them an email.

4. The change description field is not required, but should be.

5. I don't see how to change the permissions of a directory.

1. The help link in the footer doesn't work.

2. Autocomplete of the chips doesn't show existing values.

3. You shouldn't be able to @-flag yourself. Nor should you be able to self-reference the page you're currently on.

1. Clicking subscribe does something in the backend, but it doesn't change to an unsubscribe button in the UI

1. When editing a page, don't populate the change message field with the past value or else users will just accept that.

1. To prevent url collisions, all pages and directories should go under the /c/ path (this stands for content). User-related pages should go under /u/ (for user).

1. JavaScript should never be in the HTML. External files only.

1. How do you see the history of a page?

1. The description of a directory should use the same editor with all the same features as the page content.

1. Remove autocomplete on fields where it doesn't make sense like the search box, the title field, etc.

1. Remove all hard coded URLs and always use reverse, except in JavaScript, which is hopeless.

1. Make the page permissions more configurable. Instead of making a page restricted, make it so that you can add groups and users to view, edit, or admin the page.

1. Show the creator, owners, and editors of each page.

1. If you @-flag somebody in a message, don't auto-subcsribe them. Just make sure they can access the page, and send them an email with the context. If they cannot access the page, prompt the user to give them access, telling the user something like, "you tagged XYZ. They don't have access to this page. Include them now?" and then let the user choose to give that person read or write access to the page. If access is not granted, do not notify the person that they were tagged.

1. For markdown preview do two tabs on the editor, like Github.

Why doesn't the Court subdirectory appear on the homepage? It shows up in the dropdown when creating a new page?

When creating a new page, the cursor should begin in the Location field, not the title field.

1. Provide a better error when creating duplicate directory names.

Don't show my username in the upper right, since it does nothing and I know who I am.

I don't see any button or affordance for creating new groups.

1. When creating a private page, with somebody tagged in the page the permissions modal should pop up to encourage sharing with that user.

1. When typing a page location, pressing slash should have the same effect as pressing tab so that it creates the chip.

1. When searchable page content is updated or created, update the search index right then. Keep the management command, but we'll only use it manually going forward.

1. Move the sorting buttons above the files in the directory, on the right side.

2. Move the groups configuration into the admin page.

1. Implement TOC scroll-tracking highlight — "should maintain the user's location as they scroll"

1. Add a link to the diff in subscription emails

1. Add another permission for pages that are not publicly accessible, but that can be seen by anybody that is logged in. Call it "FLP View Only" or similar.

1. Add one-click unsubscription email headers to notification emails instead of links that lead to form POSTs. Use CourtListener's code as a model if needed.

1. Write a help file explaining how to use gravatar and include links to help people set it up.

1. Another permission is also needed for pages that all of FLP staff can edit.

1. Create a system for people without edit rights to propose changes to pages they can view. Some sort of affordance should be provided to users, and when changes are complete they should be emailed to the page owner for review. The page owner can then accept the changes, tweak them, and then accept them, or deny them. Once the action is taken, the proposer is notified of the decision if they shared their email address when making the proposal (or if they're an FLP user). If their change is denied, a reason provided by the page owner can be sent to the user as well.  

1. Add permission configuration and affordance to the root node.

1. Use v1, v2, etc, instead of r1, r2, etc for the different versions of a page.

1. Do not allow a page to be deleted if other pages or directories link to it. Instead, tell the user that the other page need to be updated first, and provide a list of the pages that need to be updated.

1. Change FLP View Only to "FLP Staff". That should make sense since it's in a drop down labeled "Visibility". Change "FLP Editable" to "FLP Staff" for the same reason.

1. Allow users to be archived by admins. Archiving a user logs them out and they cannot log back in until they are unarchived by an admin.

1. Create a claude.md file that requires pre-commit and that imports are at the top of every file, not inline. Check out CourtListener's claude.md file for guidance and other best practices.

1. When somebody pastes an image into the editor, use django-storages to upload that to S3. Then use signed URLs to make that available to people when the page loads. Ask me questions about how to implement this if it's not obvious.  

1. Directories have history too and it should have all the same features as pages that make sense.

1. The "Compare Selected" button no longer works to compare pages. Clicking it seems to do nothing.

1. Clicking "Unsubscribe" no longer changes the button to say "Subscribe" so that you can immediately resubscribe to a page. Refreshing the page works, but we can do better.

1. Add documentation for file uploads. Note that storage is limited to 1GB per file (and limit it accordingly).

1. Add an affordance to all editors so users can click an icon, link, button, etc in order to select something they want to upload into the post.

1. Create the needed management commands to handle any cleanup that might be needed in Django.

1. CSP and rate limiting

2. How do files get accessed? This needs a more careful review. There's some sort of file_serve function that makes me nervous that we're not using S3 properly.

1. Reverting a directory shouldn't change permissions. The docs say it does. Fix the code and

2. Add a button to the pages to copy their contents as markdown.

3. Use a worktree to convert the cronjobs into a daemon. Ask whatever questions are needed to make that work.

Do an SEO review to make pages rank really well. Use HTTP headers and HTML meta tags to save on crawl budget. Ensure that private pages don't wind up in google results. Add open graph content, and suggest other ideas that would help. We want this to be really good. Use sub-agents for parts that make sense to do separately, like robots.txt. Use a worktree.

Make it so the alert pops up when you're leaving a page you're in the middle of editing.


1. Add a feature so that users can provide feedback on the page. Integrate this into the propose changes feature so people have the choice of proposing changes or just saying what's wrong.

1. Complete another security review.

1. Make sure that sub-directories are not visible in the search sidebar facets if private

Plausible.

Ensure that all imports are at the top and add that requirement to CLAUD.md if needed.

When editing a page, show the title the page being edited. When you're making a new page, update the HTML title as the user types.

Show all the inbound links to the page in a "What links here?" kind of tool.

Use a worktree to add a page that shows all the recent changes. Use the same template/page to show user contributions if you click on somebody's name on any page, so you can filter to only their contributions. Make it private to FLP staff only.

Add pilcros to each heading so users can get the anchor easily.

Links to diffs in emails look like this, missing a slash. These should be built using the reverse URL function: https://wiki.free.law/c/hr/policies/hra-plan-detailsdiff/1/2/

"New directory" should say "New Subdirectory"

Include the breadcrumbs when editing a page or directory.

Add soft deletion support for pages

Highlighted text in the dark theme editor needs more contrast.

Image support.

Make it possible to subscribe to a directory.

Extremely long TOC doesn't scroll

Add support for Github things like this:

> [!TIP]
> You can start building a rule in the visual editor, then switch to the JSON tab to see the generated JSON. This is a good way to learn the JSON format.

and:

> [!NOTE]
> If your rule is a single condition with an action (e.g., "block ASN 14061"), the console UI is perfectly fine. Once you start combining two or more conditions with AND/OR/NOT logic, switch to the JSON editor — it will save you time and reduce the chance of misconfiguration.

small-changes worktree:
 - Pasting a link into a wiki page shows that it will be linked, but then it doesn't work.
 - When you link to wiki.free.law, it should figure out the backlink from that.
 - If you create a directory as part of creating a page, the created directory should have the same permissions as the page.
 - seeding help pages should not override existing, but there should be a flag for that

small-changes-2:
 - No auto-complete on change messages for directories
 - Make it possible to pin pages to the top (multiple can be pinned, alphabetical follows)
 - Add .md suffix support (mind security)

small-changes-3:
 - Remove the page title from the breadcrumbs
 - Allow backticks in page titles to do inline code styling in the page heading. Note that the HTML title is updated as page titles are written, and this should work there too.
 - On the page detail view, always put the edit and actions buttons below the title, regardless of viewport size (currently it does it on smaller-sized screens)
 - Don't show aliases in the dropdown shown when typing a hash sign in the editor. Only show real pages.

 - When changing permissions on a directory, check for downstream pages and directories that previously overrode the old setting, and reset them to inherit from the new one. This should not change the access of the downstream pages, but should keep our database clean.

Sitemap.xml (mind security)

LLMs.txt: https://llmstxt.org/ (mind security; do we want to add a brief field for summarizing each page?)

 - Make it so clicking the area around the link for a page works too.

 - Doing markdown links like this should work: [foo](#slug-of-some-page), or footnote style.

 -  Add a note to the 404 page about missing pages

 - After you press a hash and find a page in the editor, pressing tab or enter should select the first item in the list and the up/down arrow keys should allow you to select different items in the list.





----------------------------------------------------------------------------
# Security review
----------------------------------------------------------------------------

1. Logged-in users cannot see pages they're not supposed to.

1. Logged out users cannot see pages that aren't public.

1. You cannot see the existence of directories or pages through any view or auto-complete if you do not have permissions to view them.


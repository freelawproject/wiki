document.addEventListener('alpine:init', () => {
  // Dropdown toggle — used in page detail and directory detail
  Alpine.data('dropdown', () => ({
    open: false,
    toggle() { this.open = !this.open },
    close() { this.open = false },
  }))

  // Permission form — user/group tab toggle
  Alpine.data('permissionForm', () => ({
    target: 'user',
    get isUser() { return this.target === 'user' },
    get isGroup() { return this.target === 'group' },
    setTarget(value) { this.target = value },
  }))

  // Proposal review — editor and deny toggles
  Alpine.data('proposalReview', () => ({
    showEditor: false,
    showDeny: false,
    toggleEditor() { this.showEditor = !this.showEditor },
    toggleDeny() { this.showDeny = !this.showDeny },
    get editorHidden() { return !this.showEditor },
    get editorLabel() {
      return this.showEditor ? 'Hide editor' : 'Edit before accepting'
    },
    get denyLabel() {
      return this.showDeny ? 'Cancel' : 'Deny Proposal'
    },
  }))
})

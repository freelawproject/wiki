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

  // Copy page markdown to clipboard
  Alpine.data('copyMarkdown', () => ({
    label: 'Copy Page',
    copy(event) {
      event.stopPropagation()
      var el = document.getElementById('page-markdown-source')
      if (!el) return
      var self = this
      navigator.clipboard.writeText(el.value).then(function() {
        self.label = 'Copied!'
        setTimeout(function() {
          self.label = 'Copy Page'
          document.body.click()
        }, 1000)
      })
    },
  }))

  // Search tips toggle
  Alpine.data('searchTips', () => ({
    open: false,
    toggle() { this.open = !this.open },
    get buttonLabel() {
      return this.open ? 'Hide search tips' : 'Search tips'
    },
  }))

  // Search sort dropdown
  Alpine.data('searchSort', () => ({
    change(event) {
      var url = new URL(window.location.href)
      url.searchParams.set('sort', event.target.value)
      url.searchParams.delete('page')
      window.location.href = url.toString()
    },
  }))

  // Search date range preset filter
  Alpine.data('searchDates', () => ({
    applyPreset(event) {
      var days = parseInt(event.currentTarget.getAttribute('data-days'), 10)
      var d = new Date()
      d.setDate(d.getDate() - days)
      var url = new URL(window.location.href)
      url.searchParams.set('after', d.toISOString().slice(0, 10))
      url.searchParams.delete('before')
      url.searchParams.delete('page')
      window.location.href = url.toString()
    },
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

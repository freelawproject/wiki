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

  // Subscribe toggle — POST via fetch, show banner at top of page
  Alpine.data('subscribeToggle', () => ({
    label: '',
    subscribed: false,
    url: '',
    subscribeMsg: '',
    unsubscribeMsg: '',
    init() {
      this.subscribed = this.$el.getAttribute('data-subscribed') === 'true'
      this.url = this.$el.getAttribute('data-url')
      this.subscribeMsg = this.$el.getAttribute('data-subscribe-msg') || 'Subscribed!'
      this.unsubscribeMsg = this.$el.getAttribute('data-unsubscribe-msg') || 'Unsubscribed!'
      this.label = this.subscribed ? 'Unsubscribe' : 'Subscribe'
    },
    toggle(event) {
      event.stopPropagation()
      var self = this
      var hxHeaders = document.body.getAttribute('hx-headers')
      var csrfToken = hxHeaders ? JSON.parse(hxHeaders)['X-CSRFToken'] : ''
      fetch(self.url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
        },
      }).then(function() {
        self.subscribed = !self.subscribed
        self.label = self.subscribed ? 'Unsubscribe' : 'Subscribe'
        var msg = self.subscribed ? self.subscribeMsg : self.unsubscribeMsg
        self._showBanner(msg)
        document.body.click()
      })
    },
    _showBanner(text) {
      // Fixed-position toast at the top of the viewport
      var toast = document.createElement('div')
      toast.className = 'toast-banner alert alert-success'
      toast.setAttribute('role', 'alert')

      var span = document.createElement('span')
      span.innerHTML = text
      toast.appendChild(span)

      var btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'toast-dismiss'
      btn.setAttribute('aria-label', 'Dismiss')
      btn.innerHTML = '&#215;'
      btn.addEventListener('click', function() {
        toast.style.transition = 'opacity 0.2s'
        toast.style.opacity = '0'
        setTimeout(function() { toast.remove() }, 200)
      })
      toast.appendChild(btn)

      document.body.appendChild(toast)
    },
  }))

  // Pin toggle — POST via fetch, swap icon without page reload
  Alpine.data('pinToggle', () => ({
    pinned: false,
    url: '',
    init() {
      this.pinned = this.$el.getAttribute('data-pinned') === 'true'
      this.url = this.$el.getAttribute('data-url')
    },
    toggle() {
      var self = this
      var hxHeaders = document.body.getAttribute('hx-headers')
      var csrfToken = hxHeaders ? JSON.parse(hxHeaders)['X-CSRFToken'] : ''
      fetch(self.url, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
        },
      }).then(function(resp) {
        return resp.json()
      }).then(function(data) {
        self.pinned = data.is_pinned
      })
    },
    get title() {
      return this.pinned ? 'Unpin' : 'Pin'
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

  // Search chips — converts typed filter:value tokens into visual chips
  Alpine.data('searchChips', () => ({
    chips: [],
    focused: false,
    dirPath: '',
    dirTitle: '',
    dropdownVisible: false,

    init() {
      this.dirPath = this.$el.getAttribute('data-dir-path') || ''
      this.dirTitle = this.$el.getAttribute('data-dir-title') || ''
      var initial = this.$el.getAttribute('data-initial-chips')
      if (initial) {
        try { this.chips = JSON.parse(initial) } catch (e) { /* ignore */ }
      }
      this._renderChips()
    },

    get expanded() {
      return this.focused || this.chips.length > 0
    },

    get wrapperMaxWidth() {
      var exp = this.expanded
      return {
        'max-w-3xl': exp,
        'max-w-[12rem]': !exp,
        'lg:max-w-[14rem]': !exp,
      }
    },

    get showDirDropdown() {
      if (!this.dropdownVisible || !this.dirPath) return false
      for (var i = 0; i < this.chips.length; i++) {
        if (this.chips[i].key === 'in') return false
      }
      return true
    },

    onFocus() {
      this.focused = true
      this._updateDropdown()
    },

    onBlur() {
      this.focused = false
      this.dropdownVisible = false
    },

    onInput() {
      this._detectChips()
      this._updateDropdown()
    },

    onKeydown(event) {
      if (event.key === 'Enter' && this.showDirDropdown) {
        event.preventDefault()
        this.applyDirChip()
        return
      }
      if (event.key === 'Escape') {
        this.dropdownVisible = false
        this.$refs.input.blur()
        return
      }
      if (event.key === 'Backspace' && !this.$refs.input.value && this.chips.length > 0) {
        this.removeChip(this.chips.length - 1)
      }
    },

    applyDirChip() {
      this.chips.push({
        key: 'in',
        value: this.dirPath,
        label: this.dirTitle || this.dirPath,
      })
      this._renderChips()
      this.dropdownVisible = false
      this.$refs.input.focus()
    },

    removeChip(index) {
      this.chips.splice(index, 1)
      this._renderChips()
      this.$refs.input.focus()
      this._updateDropdown()
    },

    onSubmit() {
      var input = this.$refs.input
      var parts = []
      for (var i = 0; i < this.chips.length; i++) {
        parts.push(this.chips[i].key + ':' + this.chips[i].value)
      }
      var text = input.value.trim()
      if (text) parts.push(text)
      // Use a hidden field so the visible input doesn't flash raw filter text
      var hidden = document.createElement('input')
      hidden.type = 'hidden'
      hidden.name = 'q'
      this.$el.appendChild(hidden)
      hidden.value = parts.join(' ')
      input.removeAttribute('name')
    },

    _detectChips() {
      var input = this.$refs.input
      var val = input.value
      var re = /\b(title|content|in|owner|visibility|is|before|after):(\S+)\s/
      var changed = false
      var match
      while ((match = re.exec(val)) !== null) {
        this.chips.push({key: match[1], value: match[2], label: match[2]})
        val = val.slice(0, match.index) + val.slice(match.index + match[0].length)
        changed = true
      }
      if (changed) {
        input.value = val.replace(/\s{2,}/g, ' ').trim()
        this._renderChips()
      }
    },

    _updateDropdown() {
      var val = this.$refs.input.value
      if (!val && this.dirPath && this.focused) {
        var hasInChip = false
        for (var i = 0; i < this.chips.length; i++) {
          if (this.chips[i].key === 'in') { hasInChip = true; break }
        }
        this.dropdownVisible = !hasInChip
      } else {
        this.dropdownVisible = false
      }
    },

    _renderChips() {
      var container = this.$refs.chipArea
      if (!container) return
      while (container.firstChild) container.removeChild(container.firstChild)
      var self = this
      for (var i = 0; i < this.chips.length; i++) {
        ;(function(chip, index) {
          var el = document.createElement('span')
          el.className = 'inline-flex items-center gap-1 bg-primary-50 dark:bg-primary-900/30 border border-primary-200 dark:border-primary-700 rounded px-1.5 py-0.5 text-xs shrink-0'

          var keyEl = document.createElement('span')
          keyEl.className = 'text-gray-400 dark:text-gray-500'
          keyEl.textContent = chip.key + ':'
          el.appendChild(keyEl)

          var valEl = document.createElement('span')
          valEl.className = 'font-semibold text-primary-700 dark:text-primary-300 truncate max-w-[7rem]'
          valEl.textContent = chip.label || chip.value
          el.appendChild(valEl)

          var btn = document.createElement('button')
          btn.type = 'button'
          btn.className = 'text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 ml-0.5 leading-none'
          btn.setAttribute('aria-label', 'Remove ' + chip.key + ' filter')
          btn.textContent = '\u00D7'
          btn.addEventListener('click', function() { self.removeChip(index) })
          el.appendChild(btn)

          container.appendChild(el)
        })(self.chips[i], i)
      }
    },
  }))

  // Feedback tabs — comment vs propose on unified feedback page
  Alpine.data('feedbackTabs', () => ({
    tab: 'comment',

    init() {
      var active = this.$el.getAttribute('data-active-tab')
      if (active === 'propose') this.tab = 'propose'
    },

    setComment() { this.tab = 'comment' },
    setPropose() { this.tab = 'propose' },

    get isComment() { return this.tab === 'comment' },
    get isPropose() { return this.tab === 'propose' },

    get commentTabClass() {
      return this.tab === 'comment' ? 'tab-item-active' : 'tab-item'
    },
    get proposeTabClass() {
      return this.tab === 'propose' ? 'tab-item-active' : 'tab-item'
    },
  }))

  // Edit form wrapper — shows/hides Discoverability based on visibility
  Alpine.data('editForm', () => ({
    showDiscoverability: true,
    _inheritedVisibility: '',

    init() {
      this._inheritedVisibility = this.$el.getAttribute('data-inherited-visibility') || ''
      var self = this
      // Hidden input (inherit select) or plain <select> (root-level)
      var visInput = this.$el.querySelector('input[name="visibility"]')
      var visSelect = this.$el.querySelector('select[name="visibility"]')
      if (visInput) {
        visInput.addEventListener('input', function() {
          self._checkVisibility()
        })
      }
      if (visSelect) {
        visSelect.addEventListener('change', function() {
          self._checkVisibility()
        })
      }
      document.addEventListener('dir-inherit-update', function(e) {
        var visMeta = e.detail.visibility
        if (visMeta) {
          self._inheritedVisibility = visMeta.value
          self._checkVisibility()
        }
      })
      this._checkVisibility()
    },

    _checkVisibility() {
      var el = this.$el.querySelector('input[name="visibility"]')
          || this.$el.querySelector('select[name="visibility"]')
      if (!el) {
        this.showDiscoverability = true
        return
      }
      var val = el.value
      if (val === 'inherit') {
        this.showDiscoverability = this._inheritedVisibility === 'public'
      } else {
        this.showDiscoverability = val === 'public'
      }
    },
  }))

  // Custom select for inheritable settings (visibility, editability, etc.)
  // Shows the inherit option with a two-line layout: value + "Provided by X"
  // Options are rendered server-side in the template; Alpine handles state.
  Alpine.data('inheritSelect', () => ({
    open: false,
    selected: '',
    inheritDisplay: '',
    inheritSource: '',
    labelMap: {},
    focusedIndex: -1,

    init() {
      this.inheritDisplay = this.$el.getAttribute('data-inherit-display') || ''
      this.inheritSource = this.$el.getAttribute('data-inherit-source') || ''

      var input = this.$el.querySelector('input[type="hidden"]')
      if (input) this.selected = input.value

      // Build label map from server-rendered options for selectedLabel getter
      var map = {}
      this.$el.querySelectorAll('[data-option-value]').forEach(function(el) {
        map[el.getAttribute('data-option-value')] = el.textContent.trim()
      })
      // Include the inherited value (filtered from DOM to avoid duplication)
      var inheritVal = this.$el.getAttribute('data-inherit-value') || ''
      if (inheritVal && !map[inheritVal]) {
        map[inheritVal] = this.inheritDisplay
      }
      this.labelMap = map

      var fieldName = this.$el.getAttribute('data-field')

      // Update inherit metadata when the directory changes
      var self = this
      var fieldName = this.$el.getAttribute('data-field')
      if (fieldName) {
        document.addEventListener('dir-inherit-update', function(e) {
          var meta = e.detail[fieldName]
          if (!meta) return
          self.inheritDisplay = meta.display
          self.inheritSource = meta.source
          self._rebuildOptions(meta.value)
        })
      }
    },

    _rebuildOptions(newInheritValue) {
      // Update the inherit option text
      var inheritOpt = this.$el.querySelector('[data-value="inherit"]')
      if (inheritOpt) {
        var titleEl = inheritOpt.querySelector('.text-sm.font-medium')
        var sourceEl = inheritOpt.querySelector('.text-xs')
        if (titleEl) titleEl.textContent = this.inheritDisplay
        if (sourceEl) sourceEl.textContent = 'Provided by ' + this.inheritSource
      }
      // Rebuild explicit options: show all except the one matching the
      // new inherited value (it's redundant with the inherit option).
      var listbox = this.$el.querySelector('[role="listbox"]')
      if (!listbox) return
      // Remove old explicit options
      listbox.querySelectorAll('[data-option-value]').forEach(function(el) {
        el.remove()
      })
      // Re-add from labelMap, skipping the inherited value
      var self = this
      Object.keys(this.labelMap).forEach(function(val) {
        if (val === newInheritValue) return
        var div = document.createElement('div')
        div.setAttribute('role', 'option')
        div.setAttribute('data-value', val)
        div.setAttribute('data-option-value', val)
        div.setAttribute('tabindex', '-1')
        div.className = 'px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 focus:bg-gray-100 dark:focus:bg-gray-700 outline-none text-sm'
        div.textContent = self.labelMap[val]
        div.addEventListener('click', function(e) { self.pick(e) })
        listbox.appendChild(div)
      })
    },

    toggle() {
      this.open = !this.open
      if (this.open) this.focusedIndex = 0
    },

    close() {
      this.open = false
      this.focusedIndex = -1
    },

    pick(event) {
      var target = event.target.closest('[data-value]')
      if (!target) return
      var value = target.getAttribute('data-value')
      this._selectValue(value)
    },

    _selectValue(value) {
      this.selected = value
      var root = this.$root || this.$el
      var input = root.querySelector('input[type="hidden"]')
      if (input) {
        input.value = value
        // Notify parent components (e.g. editForm) of the change
        input.dispatchEvent(new Event('input', { bubbles: true }))
      }
      this.open = false
      this.focusedIndex = -1
      // Return focus to the button
      var btn = root.querySelector('button')
      if (btn) btn.focus()
    },

    _getOptions() {
      var root = this.$root || this.$el
      return root.querySelectorAll('[role="option"]')
    },

    onKeydown(event) {
      var key = event.key
      if (key === 'Escape') {
        if (this.open) {
          this.close()
          var root = this.$root || this.$el
          var btn = root.querySelector('button')
          if (btn) btn.focus()
          event.preventDefault()
        }
        return
      }
      if (key === 'ArrowDown') {
        event.preventDefault()
        if (!this.open) {
          this.open = true
          this.focusedIndex = 0
        } else {
          var options = this._getOptions()
          if (this.focusedIndex < options.length - 1) this.focusedIndex++
        }
        this._focusCurrent()
        return
      }
      if (key === 'ArrowUp') {
        event.preventDefault()
        if (this.open && this.focusedIndex > 0) {
          this.focusedIndex--
          this._focusCurrent()
        }
        return
      }
      if (key === 'Enter' || key === ' ') {
        if (this.open) {
          event.preventDefault()
          var options = this._getOptions()
          if (this.focusedIndex >= 0 && this.focusedIndex < options.length) {
            var value = options[this.focusedIndex].getAttribute('data-value')
            this._selectValue(value)
          }
        } else {
          event.preventDefault()
          this.open = true
          this.focusedIndex = 0
          var self = this
          // Need a tick for the DOM to show options
          setTimeout(function() { self._focusCurrent() }, 10)
        }
        return
      }
    },

    _focusCurrent() {
      var self = this
      setTimeout(function() {
        var options = self._getOptions()
        if (self.focusedIndex >= 0 && self.focusedIndex < options.length) {
          options[self.focusedIndex].focus()
        }
      }, 10)
    },

    get selectedLabel() {
      if (this.selected === 'inherit') return this.inheritDisplay
      return this.labelMap[this.selected] || this.selected
    },

    get showInheritSub() {
      return this.selected === 'inherit'
    },

    get inheritSubLabel() {
      return 'Provided by ' + this.inheritSource
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

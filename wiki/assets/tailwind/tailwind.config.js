module.exports = {
  darkMode: 'media',
  content: {
    relative: true,
    files: [
      /* Templates within the assets directory */
      '../templates/**/*.html',

      /* Templates in other django apps */
      '../../**/templates/**/*.html',

      /* JS files that could contain Tailwind CSS classes */
      '../static-global/js/**/*.js',

      /* Python files that generate HTML with Tailwind classes */
      '../../**/diff_utils.py',
    ],
  },
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'monospace'],
      },
      colors: {
        primary: {
          50: '#F5F3FF',
          100: '#EDE9FE',
          200: '#DDD6FE',
          300: '#C4B5FD',
          400: '#A78BFA',
          500: '#7F56D9',
          600: '#6D28D9',
          700: '#5B21B6',
          800: '#4C1D95',
          900: '#180040',
        },
        gray: {
          25: '#FCFCFD',
          50: '#F9FAFB',
          100: '#F2F4F7',
          200: '#EAECF0',
          300: '#D0D5DD',
          400: '#98A2B3',
          500: '#667085',
          600: '#475467',
          700: '#344054',
          800: '#1D2939',
          900: '#101828',
        },
      },
      maxWidth: {
        content: '960px',
      },
    },
  },
  plugins: [],
};

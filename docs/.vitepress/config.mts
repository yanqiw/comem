import { defineConfig } from 'vitepress';

export default defineConfig({
  title: 'Coordination Memory',
  description: 'Local-first coordination memory for multi-agent work.',
  base: '/comem/',
  cleanUrls: true,
  lastUpdated: true,
  head: [
    ['meta', { name: 'theme-color', content: '#0b1020' }],
    ['meta', { property: 'og:title', content: 'Coordination Memory' }],
    ['meta', { property: 'og:description', content: 'Coordination is live. Acceptance is durable.' }],
  ],
  themeConfig: {
    logo: '/mark.svg',
    siteTitle: 'Coordination Memory',
    nav: [
      { text: 'Guide', link: '/quickstart' },
      { text: 'Concepts', link: '/concepts' },
      { text: 'Tools', link: '/tools' },
      { text: 'Examples', link: '/examples' },
      { text: 'Francis Wang', link: 'https://yanqiw.github.io/' },
    ],
    sidebar: [
      {
        text: 'Start here',
        items: [
          { text: 'Overview', link: '/' },
          { text: 'Quickstart', link: '/quickstart' },
          { text: 'Examples', link: '/examples' },
        ],
      },
      {
        text: 'Understand the system',
        items: [
          { text: 'Concepts & governance', link: '/concepts' },
          { text: 'Tool reference', link: '/tools' },
          { text: '90-second demo', link: '/demo-script' },
        ],
      },
      {
        text: 'Project',
        items: [
          { text: 'Documentation index', link: '/README' },
          { text: 'GitHub repository', link: 'https://github.com/yanqiw/comem' },
          { text: 'PyPI package', link: 'https://pypi.org/project/coordination-memory-mcp/' },
        ],
      },
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/yanqiw/comem' }],
    editLink: {
      pattern: 'https://github.com/yanqiw/comem/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    footer: {
      message: 'Local-first. Append-only. Integrator accepted.',
      copyright: 'Released under the MIT License.',
    },
    search: { provider: 'local' },
  },
});

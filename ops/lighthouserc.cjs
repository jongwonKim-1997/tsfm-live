module.exports = {
  ci: {
    collect: {
      staticDistDir: './dist',
      url: ['http://localhost/', 'http://localhost/models/', 'http://localhost/indicators/'],
      numberOfRuns: 3,
      settings: { formFactor: 'mobile', chromeFlags: '--lang=en-US --accept-lang=en-US', screenEmulation: { mobile: true, width: 390, height: 844, deviceScaleFactor: 1, disabled: false } },
    },
    assert: {
      assertions: {
        'categories:performance': ['error', { minScore: 0.90, aggregationMethod: 'median-run' }],
        'categories:accessibility': ['error', { minScore: 0.95, aggregationMethod: 'median-run' }],
      },
    },
    upload: { target: 'filesystem', outputDir: '.lighthouseci/report' },
  },
};
